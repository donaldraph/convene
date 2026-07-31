#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { DataStack } from '../lib/data-stack';
import { ApiStack } from '../lib/api-stack';
import { HostingStack } from '../lib/hosting-stack';

const app = new cdk.App();

// Stage drives naming and prod-vs-dev behaviour. Override: cdk deploy --all -c stage=prod
const stage = app.node.tryGetContext('stage') || 'dev';

const env: cdk.Environment = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION || 'us-east-1',
};

const prefix = `cv-${stage}`;

// Storage layer - the one table every other stack reads and writes.
const data = new DataStack(app, `${prefix}-data`, { env, stage });

// Compute + API - calendar sync, conflict detection, recommendations, tasks.
const api = new ApiStack(app, `${prefix}-api`, { env, stage, table: data.table });

// Static hosting - S3 + CloudFront for the dashboard, fed the API base URL.
new HostingStack(app, `${prefix}-hosting`, { env, stage, apiUrl: api.api.url });

cdk.Tags.of(app).add('project', 'convene');
cdk.Tags.of(app).add('stage', stage);
