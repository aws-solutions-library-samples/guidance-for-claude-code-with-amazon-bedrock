export interface LandingPageConfig {
  profileName: string;
  idcInstanceArn: string;
  customDomain?: string;
  hostedZoneId?: string;
  vpcId?: string;
  region?: string;
  account?: string;
  bootstrapOidcClientId?: string;
}

export const config: LandingPageConfig = {
  profileName: 'idc-test',
  idcInstanceArn: 'arn:aws:sso:::instance/ssoins-7223f51cdbb8a24d',
  region: 'us-east-1',
  account: '343218218212',
  bootstrapOidcClientId: '',
};

export function validateConfig(cfg: LandingPageConfig): void {}
