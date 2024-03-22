from logging import getLogger
import io
import time
import os
import datetime
import boto3
import pandas
from botocore.exceptions import ClientError
from dateutil.relativedelta import relativedelta

logger = getLogger()

# athena constant
DATABASE = os.getenv('AthenaDatabase')
TABLE = os.getenv('AthenaTable')
# query constant
COLUMN = \
    'line_item_usage_account_id AS "Account Id", ' \
    'line_item_legal_entity AS "Legal Entity", ' \
    'SUM(savings_plan_net_savings_plan_effective_cost) AS "Amount (USD)"'
# S3 constant
S3_ATHENA_OUTPUT_BUCKET = os.getenv('AthenaQueryResultBucket') # Need to enter a value of bucket to output query results
S3_ATHENA_OUTPUT_KEY_DIR = os.getenv('AthenaQueryResultDir')
S3_ATHENA_OUTPUT = 's3://' + S3_ATHENA_OUTPUT_BUCKET + '/' + S3_ATHENA_OUTPUT_KEY_DIR
S3_CSV_OUTPUT_BUCKET = os.getenv('CSVOutputBucket') # csv output destination for final outputs
# number of retries
RETRY_COUNT = 10
# SP Purchase Account ID
SP_PURCHASE_ACCOUNT_ID = os.getenv('SPPurchaseAccountID')
# Saving Planss ID for aggregation
SP_ID = 'arn:aws:savingsplans::' + SP_PURCHASE_ACCOUNT_ID + ':savingsplan/%' # Need to enter a value of Account ID that purchased the SP
# Root OU ID to obtain a list of accounts
ROOT_OU_ID = os.getenv('RootOUId')
# tax rate 10%
TAX_RATE = 0.1

def exec_athena(start_year, start_month):
    """Aggregate only SPs costs with Athena

    Returns
    -------
    query_execution_ids : str
        Athena query execution ID 
    """
    logger.info('Starting a query using Athena')
    aggregation_year = f'\'{start_year}\''
    aggregation_month = f'\'{start_month}\''
    line_item_type = '\'SavingsPlanCoveredUsage\''
    savings_plan_a_r_n = f'\'{SP_ID}\''
    # created query
    query = f'SELECT {COLUMN} FROM {DATABASE}.{TABLE} ' \
            f'WHERE year = {aggregation_year} and month = {aggregation_month} and line_item_line_item_type = {line_item_type} ' \
            f'AND savings_plan_savings_plan_a_r_n LIKE {savings_plan_a_r_n} ' \
            f'GROUP BY line_item_usage_account_id, line_item_legal_entity'
    logger.info('The query parameter is')
    logger.info(query)
    # athena client
    client = boto3.client('athena', region_name='ap-northeast-1')
    # Execution
    logger.info('Query execution start')
    response = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={
            'Database': DATABASE
        },
        ResultConfiguration={
            'OutputLocation': S3_ATHENA_OUTPUT,
        }
    )
    # get query execution id
    query_execution_id = response['QueryExecutionId']
    # get execution status
    for i in range(1, 1 + RETRY_COUNT):
        # get query execution
        query_status = client.get_query_execution(QueryExecutionId=query_execution_id)
        query_execution_status = query_status['QueryExecution']['Status']['State']
        if query_execution_status == 'SUCCEEDED':
            logger.info("STATUS:" + query_execution_status)
            break
        if query_execution_status == 'FAILED':
            raise Exception("STATUS:" + query_execution_status)
        else:
            logger.info("STATUS:" + query_execution_status)
            time.sleep(i)
    else:
        client.stop_query_execution(QueryExecutionId=query_execution_id)
        raise Exception('TIME OVER')
    # get query results
    logger.info('Query execution complete')
    logger.info('execution id is ' + query_execution_id)
    return query_execution_id

def get_cost_csv_from_s3(key, bucket):
    """Get Cost CSV"""
    logger.info('Start getting a csv from S3 bucket')
    logger.info(f'The target csv is {bucket}/{key}')
    s3 = boto3.client('s3')
    response = s3.get_object(Bucket=bucket, Key=key)
    body = response['Body'].read().decode('utf-8')
    buffer_in = io.StringIO(body)
    logger.info('Getting the csv is completed')
    return buffer_in

def upload_s3(output, key, bucket):
    """Upload csv to S3"""
    try:
        logger.info('Start uploading files to S3')
        s3_resource = boto3.resource('s3')
        s3_bucket = s3_resource.Bucket(bucket)
        s3_bucket.upload_file(output, key, ExtraArgs={'ACL': 'bucket-owner-full-control'})
        logger.info('Uploading files to S3 is completed')
    except ClientError as err:
        logger.error(err.response['Error']['Message'])
        raise

def add_tax_to_sp_csv(csv_df):
    """Add tax to the amounts charged in the csv"""
    logger.info('Start adding tax to the amount of the csv')
    logger.info(f'tax rate is {1.0+TAX_RATE}')
    modified_csv_df=csv_df.copy()
    modified_csv_df['Amount (USD)']=modified_csv_df['Amount (USD)'].astype(float).apply(lambda x: x * (1.0+TAX_RATE))
    logger.info('Complete adding tax to the csv')
    return modified_csv_df

def get_ou_ids(org, parent_id):
    """Get OU ids"""
    ou_ids = []
    try:
        paginator = org.get_paginator('list_children')
        iterator = paginator.paginate(
            ParentId=parent_id,
            ChildType='ORGANIZATIONAL_UNIT'
        )
        for page in iterator:
            for ou in page['Children']:
                ou_ids.append(ou['Id'])
                ou_ids.extend(get_ou_ids(org, ou['Id']))
    except ClientError as err:
        logger.error(err.response['Error']['Message'])
        raise
    else:
        return ou_ids

def list_accounts():
    """Get Account List"""
    org = boto3.client('organizations')
    root_id = ROOT_OU_ID
    ou_id_list = [root_id]
    ou_id_list.extend(get_ou_ids(org, root_id))
    accounts = []
    try:
        for ou_id in ou_id_list:
            paginator = org.get_paginator('list_accounts_for_parent')
            page_iterator = paginator.paginate(ParentId=ou_id)
            for page in page_iterator:
                for account in page['Accounts']:
                    item = [
                        account['Id'],
                        account['Name'],
                    ]
                    accounts.append(item)
    except ClientError as err:
        logger.error(err.response['Error']['Message'])
        raise
    else:
        return accounts

def process_sp_csv_by_pandas(only_sp_cost_csv):
    """Process csv with SP only aggregated"""
    sp_cost_csv_df = pandas.read_csv(only_sp_cost_csv, dtype=object)
    # Getting a list of account names in this organization
    account_list_df = pandas.DataFrame(list_accounts(), columns=['Account Id', 'Account Name'])
    # Associate the name with the account ID that is using the SPs
    account_name_merged_sp_cost_df = pandas.merge(account_list_df, sp_cost_csv_df, on='Account Id', how='inner')
    logger.info('Processing Athena query results is completed')
    # Add tax due to the need to transfer costs, including tax.
    merged_sp_cost_with_tax_df = add_tax_to_sp_csv(account_name_merged_sp_cost_df)
    merged_sp_cost_with_tax_df.to_csv('/tmp/sp_with_tax.csv', index=False)
    return merged_sp_cost_with_tax_df


def lambda_handler(event, context):
    """main"""
    logger.info('Start Savings Plans usage aggregation')
    # aggregation period (last month)
    today = datetime.date.today()
    last_month = today - relativedelta(months=1)
    dir_start_year = last_month.strftime('%Y')
    dir_start_month = last_month.strftime('%m')

    # Do not be zero-paddeing for the value of months used in Athena query.
    quary_exec_id = exec_athena(last_month.year, last_month.month)
    logger.info('Start processing Athena query results')
    only_sp_cost_csv = get_cost_csv_from_s3(S3_ATHENA_OUTPUT_KEY_DIR+quary_exec_id+'.csv', S3_ATHENA_OUTPUT_BUCKET)
    merged_sp_cost_with_tax_df = process_sp_csv_by_pandas(only_sp_cost_csv)
    upload_s3('/tmp/sp_with_tax.csv',
              f'{dir_start_year}-{dir_start_month}/sp-costs-{dir_start_year}-{dir_start_month}.csv',
              S3_CSV_OUTPUT_BUCKET)
    logger.info('Savings Plans usage aggregation is completed')
