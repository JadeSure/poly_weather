#!/usr/bin/env python3
import aws_cdk as cdk
from stack import PolyWeatherStack

app = cdk.App()

PolyWeatherStack(
    app,
    "PolyWeatherStack",
    # Override via CDK_DEFAULT_ACCOUNT / CDK_DEFAULT_REGION env vars, or
    # pass --context account=... --context region=... on the CLI.
    env=cdk.Environment(
        account=app.node.try_get_context("account") or None,
        region=app.node.try_get_context("region") or "ap-southeast-2",  # Singapore
    ),
)

app.synth()
