import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';

interface DataStackProps extends cdk.StackProps {
  stage: string;
}

/**
 * Storage layer - one DynamoDB table, single-table design keyed by a typed PK.
 *
 *   PK                SK                       what it is
 *   ---------------   ----------------------   ---------------------------------------------
 *   EVENT#<source>    <startUTC>#<eventId>     cached calendar event; source = academic | community
 *   SYNC              <source>                 last-sync metadata per calendar (when, how many)
 *   CONFLICT          <conflictId>             a detected academic/community collision + status
 *   RECO              <requestedAt>            a best-time request and Gemini's recommendation
 *   TASK              <taskId>                 a team task: assignee, due date, status
 *   MEMBER            <name>                   core-team roster entry (reminder targets)
 *
 * Reads the app needs, all single-partition Queries:
 *   events in a window   -> Query(PK=EVENT#x, SK between startA and startB)
 *   open conflicts       -> Query(PK=CONFLICT), filter status
 *   task board           -> Query(PK=TASK)
 * One partition per type is fine: one group, one leader, a few dozen events.
 */
export class DataStack extends cdk.Stack {
  public readonly table: dynamodb.Table;

  constructor(scope: Construct, id: string, props: DataStackProps) {
    super(scope, id, props);
    const isProd = props.stage === 'prod';

    this.table = new dynamodb.Table(this, 'Convene', {
      tableName: `cv-convene-${props.stage}`,
      partitionKey: { name: 'PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'SK', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: isProd,
      removalPolicy: isProd ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
    });

    new cdk.CfnOutput(this, 'TableName', { value: this.table.tableName });
  }
}
