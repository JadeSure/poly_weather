"""CDK stack: poly-weather (API + worker) on EC2 with a fresh VPC and SSM access."""

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_logs as logs,
)
from constructs import Construct

REPO = "https://github.com/JadeSure/poly_weather.git"
INSTANCE_TYPE = ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.SMALL)


class PolyWeatherStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── VPC ───────────────────────────────────────────────────────────────
        # Two public subnets across 2 AZs + Internet Gateway.
        # EC2 placed in a public subnet so it can reach external APIs directly
        # (no NAT Gateway cost). All inbound traffic is blocked by the SG.
        vpc = ec2.Vpc(
            self,
            "PolyWeatherVpc",
            vpc_name="poly-weather-vpc",
            ip_addresses=ec2.IpAddresses.cidr("10.11.0.0/16"),
            max_azs=2,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                )
            ],
            nat_gateways=0,
            enable_dns_hostnames=True,
            enable_dns_support=True,
        )

        # ── Security group ────────────────────────────────────────────────────
        # No inbound rules – SSM Session Manager uses outbound HTTPS only.
        # Use `aws ssm start-session --target <id>` or port-forward for API access.
        sg = ec2.SecurityGroup(
            self,
            "PolyWeatherSg",
            vpc=vpc,
            security_group_name="poly-weather-sg",
            description="Poly Weather EC2 - outbound-only (SSM access)",
            allow_all_outbound=True,  # HTTPS to Polymarket, NOAA, OpenMeteo, etc.
        )
        sg.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(8000),
            "FastAPI port",
        )

        # ── IAM role ──────────────────────────────────────────────────────────
        role = iam.Role(
            self,
            "PolyWeatherRole",
            role_name="poly-weather-ec2-role",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonSSMManagedInstanceCore"
                ),
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "CloudWatchAgentServerPolicy"
                ),
            ],
            inline_policies={
                "StaxSsmS3Access": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=[
                                "s3:GetEncryptionConfiguration",
                                "s3:PutObject",
                                "s3:GetObject",
                                "s3:AbortMultipartUpload",
                                "s3:ListMultipartUploadParts",
                            ],
                            resources=[
                                "arn:aws:s3:::stax-session-manager-ab2f12c0-4646-405f-a0d5-b24d5e436121",
                                "arn:aws:s3:::stax-session-manager-ab2f12c0-4646-405f-a0d5-b24d5e436121/*",
                            ],
                        )
                    ]
                )
            },
        )

        # ── CloudWatch log groups ─────────────────────────────────────────────
        api_log_group = logs.LogGroup(
            self,
            "ApiLogGroup",
            log_group_name="/poly-weather/api",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        worker_log_group = logs.LogGroup(
            self,
            "WorkerLogGroup",
            log_group_name="/poly-weather/worker",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # ── User data ─────────────────────────────────────────────────────────
        user_data_path = Path(__file__).parent / "user_data" / "setup.sh"
        user_data = ec2.UserData.for_linux()
        user_data.add_commands(user_data_path.read_text())

        # ── EC2 instance ──────────────────────────────────────────────────────
        instance = ec2.Instance(
            self,
            "PolyWeatherInstance",
            instance_name="poly-weather",
            vpc=vpc,
            instance_type=INSTANCE_TYPE,
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            security_group=sg,
            role=role,
            user_data=user_data,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            associate_public_ip_address=True,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(
                        20,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        encrypted=True,
                        delete_on_termination=True,
                    ),
                ),
                # Persistent EBS volume for SQLite data (survives instance replacement)
                ec2.BlockDevice(
                    device_name="/dev/xvdf",
                    volume=ec2.BlockDeviceVolume.ebs(
                        50,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        encrypted=True,
                        delete_on_termination=False,
                    ),
                ),
            ],
        )

        # ── Outputs ───────────────────────────────────────────────────────────
        cdk.CfnOutput(self, "InstanceId", value=instance.instance_id)
        cdk.CfnOutput(self, "VpcId", value=vpc.vpc_id)
        cdk.CfnOutput(
            self,
            "SsmConnectCommand",
            value=f"aws ssm start-session --target {instance.instance_id}",
            description="Connect to the instance via SSM (no SSH key needed)",
        )
        cdk.CfnOutput(
            self,
            "SsmPortForwardApi",
            value=f"aws ssm start-session --target {instance.instance_id} --document-name AWS-StartPortForwardingSession --parameters portNumber=8000,localPortNumber=8000",
            description="Forward API port 8000 to localhost via SSM",
        )
        cdk.CfnOutput(self, "ApiLogGroupName", value=api_log_group.log_group_name)
        cdk.CfnOutput(self, "WorkerLogGroupName", value=worker_log_group.log_group_name)
