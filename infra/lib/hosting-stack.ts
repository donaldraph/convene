import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as path from 'path';

interface HostingStackProps extends cdk.StackProps {
  stage: string;
  apiUrl: string;
}

/**
 * Static hosting for the dashboard. A private S3 bucket (all public access
 * blocked) behind CloudFront with Origin Access Control, on the default
 * CloudFront domain. The API base URL is written in as config.js at deploy,
 * so the frontend never hardcodes it.
 */
export class HostingStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: HostingStackProps) {
    super(scope, id, props);
    const isProd = props.stage === 'prod';
    const removal = isProd ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY;

    const siteBucket = new s3.Bucket(this, 'SiteBucket', {
      bucketName: `cv-web-${props.stage}-${this.account}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy: removal,
      autoDeleteObjects: !isProd,
    });

    const dist = new cloudfront.Distribution(this, 'SiteDist', {
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(siteBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
      },
      defaultRootObject: 'index.html',
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
    });

    new s3deploy.BucketDeployment(this, 'DeployWeb', {
      sources: [
        s3deploy.Source.asset(path.join(__dirname, '..', '..', 'web')),
        // Inject the API base so the frontend does not hardcode it.
        s3deploy.Source.data('config.js', `window.CV_API_BASE = ${JSON.stringify(props.apiUrl)};`),
      ],
      destinationBucket: siteBucket,
      distribution: dist,
      distributionPaths: ['/*'],
    });

    new cdk.CfnOutput(this, 'SiteUrl', { value: `https://${dist.distributionDomainName}` });
    new cdk.CfnOutput(this, 'DistributionId', { value: dist.distributionId });
  }
}
