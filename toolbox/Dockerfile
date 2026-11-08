# The deploy toolbox: Terraform, the AWS CLI, the Session Manager plugin and a few tools, so the scripts
# behave the same on Windows, macOS and Linux. Built automatically by the scripts on first use.
# It never sees ~/.aws: the scripts pass in short-lived credentials of the deploy role.
FROM debian:bookworm-slim

ARG TERRAFORM_VERSION=1.16.7
ARG AWSCLI_VERSION=2.38.6
ARG SSM_PLUGIN_VERSION=1.2.889.0
ARG TARGETARCH

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl unzip git jq socat less \
    && rm -rf /var/lib/apt/lists/*

SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

# Terraform (checked against HashiCorp's published checksums), AWS CLI v2, Session Manager plugin.
RUN arch="${TARGETARCH:-amd64}"; \
    case "$arch" in \
      amd64) tf=amd64; cli=x86_64; ssm=ubuntu_64bit ;; \
      arm64) tf=arm64; cli=aarch64; ssm=ubuntu_arm64 ;; \
      *) echo "Unsupported architecture: $arch" >&2; exit 1 ;; \
    esac; \
    cd /tmp; \
    curl -fsSLO "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${tf}.zip"; \
    curl -fsSLO "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_SHA256SUMS"; \
    grep "_linux_${tf}.zip" "terraform_${TERRAFORM_VERSION}_SHA256SUMS" | sha256sum -c -; \
    unzip -q "terraform_${TERRAFORM_VERSION}_linux_${tf}.zip" -d /usr/local/bin; \
    curl -fsSL -o awscli.zip "https://awscli.amazonaws.com/awscli-exe-linux-${cli}-${AWSCLI_VERSION}.zip"; \
    unzip -q awscli.zip; ./aws/install; \
    curl -fsSL -o ssm.deb "https://s3.amazonaws.com/session-manager-downloads/plugin/${SSM_PLUGIN_VERSION}/${ssm}/session-manager-plugin.deb"; \
    dpkg -i ssm.deb; \
    rm -rf /tmp/*; \
    terraform version; aws --version; session-manager-plugin --version

# The repo is mounted at /work and may be owned by another user id.
RUN git config --system --add safe.directory /work
ENV HOME=/tmp AWS_PAGER="" TF_IN_AUTOMATION=1 TF_INPUT=0
WORKDIR /work
