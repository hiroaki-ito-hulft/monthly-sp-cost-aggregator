# SP cost aggregator
## 概要
Savings Plans(SP)をあるアカウントで購入し、SPの共有によって所属組織のアカウントにSPを共有している場合、  
どのアカウントでいくらSPを使用したのか把握することが難しいです。  
それを把握するためにSPのアカウントごとの利用量を計算し、csvにまとめるためのスクリプトです。  
毎月10日に前月分のcsvが出力されます。

## 前提
このスクリプトを使用するためにはCost and Usage Reports(CUR)の設定と、  
https://docs.aws.amazon.com/ja_jp/cur/latest/userguide/creating-cur.html  
CURをクエリ出来るように設定したAthenaが必要です。  
https://docs.aws.amazon.com/ja_jp/cur/latest/userguide/cur-query-athena.html  
また、SPのコスト集計結果csvを配置するS3バケットをあらかじめ作成する必要があります。

## 事前準備
AWS SAMを使用します。
そのため、SAMでアプリケーションを構築する上で必要なパラメータをsamconfig.tomlに記載する必要があります。
* stack_name  
SAMでデプロイされるCloudFormationのスタック名
* AthenaDatabase, AthenaTable  
CURをクエリするために設定したAthenaのデータベース、テーブル名
* AthenaQueryResultBucket, AthenaQueryResultDir  
Athenaのクエリ結果を格納するバケット、ディレクトリ名
* CURBucket  
CURの結果の出力先のバケット名
* CSVOutputBucket  
SPのコストを集計したcsvを出力する先のバケット名
* EventBridgeName  
集計処理を実行するLambdaを起動するEventBridge スケジューラーの名前
* LambdaFunctionName  
集計処理を実行するLambda関数名
* SPPurchaseAccountID  
共有しているSPを購入したAWS Account ID
* ROOT_OU_ID  
アカウントのリスト取得のためのOU ID

## アプリケーションのデプロイ方法
dockerがインストールされている環境であれば以下のコマンドを実行するのみで問題ないです。  
1. sam build -u
2. sam deploy --resolve-s3

dockerをインストールできない場合はPython3.11, pip3.11をインストールしてから  
以下のコマンドを実行してください。  
1. sam build
2. sam deploy --resolve-s3

以上です。