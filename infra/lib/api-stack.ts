import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigw from 'aws-cdk-lib/aws-apigateway';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as path from 'path';

// Secret names are fixed here so every phase wires the same ones. Created out of
// band (never in CloudFormation, so a stack delete cannot take a credential with it):
//   convene/gemini        { "api_key": ... }
//   convene/google-oauth  { "client_id": ..., "client_secret": ..., "refresh_token": ... }
//   convene/telegram      { "bot_token": ..., "chat_id": ... }
export const GEMINI_SECRET_NAME = 'convene/gemini';
export const GOOGLE_OAUTH_SECRET_NAME = 'convene/google-oauth';
export const TELEGRAM_SECRET_NAME = 'convene/telegram';

interface ApiStackProps extends cdk.StackProps {
  stage: string;
  table: dynamodb.Table;
}

/**
 * Compute + API. Scaffold ships exactly one real route, GET /health, so the
 * deployed URL proves the whole chain (API GW -> Lambda -> Dynamo env) works.
 * Calendar sync, conflict detection, recommendations, tasks, and the
 * EventBridge schedule each land with the phase that implements them.
 */
export class ApiStack extends cdk.Stack {
  public readonly api: apigw.RestApi;

  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);
    const { table } = props;

    const lambdasPath = path.join(__dirname, '..', 'lambdas');
    const commonEnv = {
      TABLE_NAME: table.tableName,
      APP_TZ: this.node.tryGetContext('appTz') || 'Africa/Lagos',
    };

    const makeFn = (
      name: string,
      handler: string,
      extraEnv: Record<string, string> = {},
      timeoutSeconds = 10,
      memoryMb = 256,
    ) =>
      new lambda.Function(this, name, {
        runtime: lambda.Runtime.PYTHON_3_12,
        code: lambda.Code.fromAsset(lambdasPath),
        handler,
        timeout: cdk.Duration.seconds(timeoutSeconds),
        memorySize: memoryMb,
        environment: { ...commonEnv, ...extraEnv },
        tracing: lambda.Tracing.ACTIVE,
      });

    const healthFn = makeFn('HealthFn', 'health.handler');
    table.grantReadData(healthFn);

    this.api = new apigw.RestApi(this, 'Api', {
      restApiName: `cv-${props.stage}`,
      deployOptions: { stageName: props.stage, tracingEnabled: true },
      defaultCorsPreflightOptions: {
        allowOrigins: apigw.Cors.ALL_ORIGINS,
        allowMethods: apigw.Cors.ALL_METHODS,
        allowHeaders: ['Content-Type', 'x-api-key'],
      },
    });

    this.api.root.addResource('health').addMethod('GET', new apigw.LambdaIntegration(healthFn));

    new cdk.CfnOutput(this, 'ApiUrl', { value: this.api.url });
  }
}
