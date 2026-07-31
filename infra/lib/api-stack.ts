import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigw from 'aws-cdk-lib/aws-apigateway';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
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

    // Calendar sync + conflict detection. 60s: two calendar fetches plus a
    // token exchange over the public internet deserve headroom, not a timeout
    // at 10s on a slow Google day.
    const oauthSecret = secretsmanager.Secret.fromSecretNameV2(
      this, 'GoogleOauthSecret', GOOGLE_OAUTH_SECRET_NAME);
    const syncFn = makeFn(
      'SyncFn',
      'sync.handler',
      {
        GOOGLE_OAUTH_SECRET_NAME,
        ACADEMIC_CAL_NAME: this.node.tryGetContext('academicCal') || 'Academic',
        COMMUNITY_CAL_NAME: this.node.tryGetContext('communityCal') || 'Community',
        SYNC_DAYS: this.node.tryGetContext('syncDays') || '30',
      },
      60,
      512,
    );
    table.grantReadWriteData(syncFn);
    oauthSecret.grantRead(syncFn);

    const getConflictsFn = makeFn('GetConflictsFn', 'get_conflicts.handler');
    table.grantReadData(getConflictsFn);

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

    // POST /sync mutates the cache and burns Google quota, so it takes an API
    // key (AWS-managed, nothing secret in the repo). GET /conflicts is a
    // public read, same reasoning as study-conscience's brief.
    this.api.root
      .addResource('sync')
      .addMethod('POST', new apigw.LambdaIntegration(syncFn), { apiKeyRequired: true });
    this.api.root
      .addResource('conflicts')
      .addMethod('GET', new apigw.LambdaIntegration(getConflictsFn));

    const key = this.api.addApiKey('OpsKey', { apiKeyName: `cv-${props.stage}-ops` });
    const plan = this.api.addUsagePlan('OpsPlan', {
      name: `cv-${props.stage}-ops`,
      throttle: { rateLimit: 5, burstLimit: 10 },
      apiStages: [{ api: this.api, stage: this.api.deploymentStage }],
    });
    plan.addApiKey(key);

    new cdk.CfnOutput(this, 'ApiUrl', { value: this.api.url });
    new cdk.CfnOutput(this, 'OpsKeyId', { value: key.keyId });
  }
}
