# Current Google Cloud Deployment

Deployment recorded on 30 August 2026 (Asia/Singapore).

## Virtual machine

- Google Cloud project: `nifty-pursuit-505911-n0`
- Instance: `dsa5208-mongodb`
- Zone: `asia-southeast1-b` (Singapore)
- Machine type: `e2-standard-2` (2 vCPU, 8 GB RAM)
- Boot disk: 30 GB balanced persistent disk
- Operating system: Ubuntu 24.04.4 LTS
- Kernel at deployment: `6.17.0-1022-gcp`

The VM's external IP is intentionally not recorded because an ephemeral address
can change after the VM is stopped and restarted.

## Software

- Docker Engine: `29.7.2`
- Docker Compose: `v5.5.0`
- MongoDB image: `mongo:8.0.29`
- MongoDB image digest:
  `sha256:02a0cc7939f5ed38f30f9bc714ef5f682d49baf9350c54acf302ce833087fe8a`
- Python runner: `python:3.12-slim`
- PyMongo: `4.17.0`

## Validation result

The initial deployment validation passed:

- `mongo1:27017`: `PRIMARY`, healthy
- `mongo2:27017`: `SECONDARY`, healthy
- `mongo3:27017`: `SECONDARY`, healthy
- Majority write followed by a causally consistent majority read: passed
- MongoDB ports are exposed only on the VM loopback interface

At validation time the VM used approximately 1.2 GiB of 7.8 GiB RAM, and the
root disk used approximately 5.5 GB of 29 GB.

## Cost control

The Google Cloud creation form estimated approximately US$0.09 per running hour
and US$3.30 per month for the persistent disk. Stop the VM in the Google Cloud
console whenever experiments are not being run. Stopping the VM ends compute
charges, but the persistent disk continues to incur storage charges.

Do not delete the VM or its disk until the experimental results and MongoDB
volumes have been backed up.
