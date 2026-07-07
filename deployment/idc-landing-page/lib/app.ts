#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { CognitoIdcStack, CognitoCallbackUpdater } from './cognito-idc-stack';
import { CloudFrontLandingPageStack } from './cloudfront-landing-page-stack';
import { config, validateConfig } from './config';

// Validate configuration
validateConfig(config);

const app = new cdk.App();

const env = {
  account: config.account || process.env.CDK_DEFAULT_ACCOUNT,
  region: config.region || process.env.CDK_DEFAULT_REGION,
};

// Stack 1: Cognito User Pool (will federate with IDC via SAML)
const cognitoStack = new CognitoIdcStack(app, `${config.profileName}-cognito`, config, {
  env,
  description: 'Cognito User Pool for Claude Code landing page with IAM Identity Center SAML federation',
});

// Stack 2: CloudFront + Lambda + S3 Landing Page
const landingPageStack = new CloudFrontLandingPageStack(app, `${config.profileName}-landing-page`, {
  env,
  description: 'Claude Code distribution landing page (CloudFront + Lambda)',
  config,
  userPool: cognitoStack.userPool,
  userPoolClient: cognitoStack.userPoolClient,
  userPoolDomain: cognitoStack.userPoolDomain,
});

// Update Cognito callback URLs with CloudFront domain
new CognitoCallbackUpdater(landingPageStack, 'CallbackUpdater', {
  userPool: cognitoStack.userPool,
  userPoolClient: cognitoStack.userPoolClient,
  cloudFrontUrl: landingPageStack.landingPageUrl,
});

// Ensure Cognito is deployed before landing page
landingPageStack.addDependency(cognitoStack);

// Tags
cdk.Tags.of(app).add('Project', 'claude-code-landing-page');
cdk.Tags.of(app).add('Profile', config.profileName);
cdk.Tags.of(app).add('ManagedBy', 'CDK');
