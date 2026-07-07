import * as cdk from 'aws-cdk-lib';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as cr from 'aws-cdk-lib/custom-resources';
import { Construct } from 'constructs';
import { LandingPageConfig } from './config';

/**
 * Cognito User Pool for IAM Identity Center SAML federation.
 *
 * NOTE: AWS does not allow creating custom SAML applications via API.
 * The SAML app must be created manually in IAM Identity Center console.
 * This stack outputs all the values needed for manual configuration.
 */
export class CognitoIdcStack extends cdk.Stack {
  public readonly userPool: cognito.UserPool;
  public readonly userPoolClient: cognito.UserPoolClient;
  public readonly userPoolDomain: cognito.UserPoolDomain;

  constructor(scope: Construct, id: string, config: LandingPageConfig, props?: cdk.StackProps) {
    super(scope, id, props);

    const prefix = config.profileName.toLowerCase().replace(/[^a-z0-9-]/g, '-');

    // Create Cognito User Pool
    this.userPool = new cognito.UserPool(this, 'UserPool', {
      userPoolName: `${prefix}-idc-bridge`,
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      standardAttributes: {
        email: { required: true, mutable: true },
      },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Create User Pool Domain
    const domainPrefix = `${prefix}-${this.account}`.substring(0, 63);
    this.userPoolDomain = this.userPool.addDomain('Domain', {
      cognitoDomain: { domainPrefix },
    });

    // SAML configuration values
    const samlAcsUrl = `https://${domainPrefix}.auth.${this.region}.amazoncognito.com/saml2/idpresponse`;
    const samlAudienceUri = `urn:amazon:cognito:sp:${this.userPool.userPoolId}`;

    // Create App Client - will use COGNITO initially, switch to SAML after manual setup
    this.userPoolClient = this.userPool.addClient('WebClient', {
      userPoolClientName: `${prefix}-web-client`,
      generateSecret: false,
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [
          cognito.OAuthScope.EMAIL,
          cognito.OAuthScope.OPENID,
          cognito.OAuthScope.PROFILE,
        ],
        callbackUrls: ['https://localhost/callback'],
        logoutUrls: ['https://localhost/logout'],
      },
      supportedIdentityProviders: [
        cognito.UserPoolClientIdentityProvider.COGNITO,
      ],
    });

    // Outputs for manual SAML configuration
    new cdk.CfnOutput(this, 'UserPoolId', {
      value: this.userPool.userPoolId,
      exportName: `${config.profileName}-UserPoolId`,
    });

    new cdk.CfnOutput(this, 'UserPoolDomain', {
      value: this.userPoolDomain.domainName,
      exportName: `${config.profileName}-UserPoolDomain`,
    });

    new cdk.CfnOutput(this, 'UserPoolClientId', {
      value: this.userPoolClient.userPoolClientId,
      exportName: `${config.profileName}-UserPoolClientId`,
    });

    new cdk.CfnOutput(this, 'SamlAcsUrl', {
      value: samlAcsUrl,
      description: 'Use this as Application ACS URL in IAM Identity Center',
    });

    new cdk.CfnOutput(this, 'SamlAudienceUri', {
      value: samlAudienceUri,
      description: 'Use this as SAML Audience in IAM Identity Center',
    });
  }
}

/**
 * Updates Cognito client callback URLs after CloudFront is created.
 */
export class CognitoCallbackUpdater extends Construct {
  constructor(
    scope: Construct,
    id: string,
    props: {
      userPool: cognito.UserPool;
      userPoolClient: cognito.UserPoolClient;
      cloudFrontUrl: string;
    }
  ) {
    super(scope, id);

    const { userPool, userPoolClient, cloudFrontUrl } = props;

    new cr.AwsCustomResource(this, 'UpdateCallbacks', {
      onCreate: {
        service: 'CognitoIdentityServiceProvider',
        action: 'updateUserPoolClient',
        parameters: {
          UserPoolId: userPool.userPoolId,
          ClientId: userPoolClient.userPoolClientId,
          CallbackURLs: [`${cloudFrontUrl}/callback`],
          LogoutURLs: [`${cloudFrontUrl}/logout`],
          AllowedOAuthFlows: ['code'],
          AllowedOAuthScopes: ['openid', 'email', 'profile'],
          AllowedOAuthFlowsUserPoolClient: true,
          SupportedIdentityProviders: ['COGNITO'],
        },
        physicalResourceId: cr.PhysicalResourceId.of(`${userPoolClient.userPoolClientId}-callbacks`),
      },
      onUpdate: {
        service: 'CognitoIdentityServiceProvider',
        action: 'updateUserPoolClient',
        parameters: {
          UserPoolId: userPool.userPoolId,
          ClientId: userPoolClient.userPoolClientId,
          CallbackURLs: [`${cloudFrontUrl}/callback`],
          LogoutURLs: [`${cloudFrontUrl}/logout`],
          AllowedOAuthFlows: ['code'],
          AllowedOAuthScopes: ['openid', 'email', 'profile'],
          AllowedOAuthFlowsUserPoolClient: true,
          SupportedIdentityProviders: ['COGNITO'],
        },
        physicalResourceId: cr.PhysicalResourceId.of(`${userPoolClient.userPoolClientId}-callbacks`),
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: ['cognito-idp:UpdateUserPoolClient'],
          resources: [userPool.userPoolArn],
        }),
      ]),
    });
  }
}
