#!/bin/bash
sudo apt-get update
sudo apt-get install -y curl jq

# Our normal path is: 
#
#    curl -L -o bowtie-service_amd64-20.04-20.04-25.06.001.deb https://api.bowtie.works/api/v1/package/4651/download/
#    sudo apt install ./bowtie-service_amd64-20.04-20.04-25.06.001.deb
#
# We're going to write a script that will get the latest version instead
#                   ("operating_system", "linux"),
#
# // Change this to 'min_os_version=24.04' when you upgrade
# 

# Get all the latest versions
PACKAGE_ID=$(curl -s "https://api.bowtie.works/api/v1/package/?operating_system=linux&package_type=deb&max_os_version=20.04" | jq -r '.[0].id')

# Pre-land your config file
sudo mkdir -p /etc/bowtie/configuration
sudo tee /etc/bowtie/configuration/config.toml > /dev/null <<EOF
entrypoint = [ "$CONTROLLER_ONE_URL", "$CONTROLLER_TWO_URL" ]
auth_prompt_strategy = "never"
EOF

curl -L -o bowtie-service_amd64.deb "https://api.bowtie.works/api/v1/package/${PACKAGE_ID}/download/"
# Install the latest version
sudo apt install -y ./bowtie-service_amd64.deb

# Get our own device ID out and annouce it to the script

# Repeat this, sleeping for a few seonds, until we get a device ID
while true; do
    DEVICE_ID=$(curl -s "http://localhost:17133/organizations/states" | jq -r '.pending_device.id')
    if [ -n "$DEVICE_ID" ]; then
        break
    fi
    echo "Waiting for device ID..."
    sleep 5
done

# Emit the device ID to our bastion/webhook kind of thing
curl -X POST "$JOIN_HELPER_URL" \
     -H "Content-Type: application/json" \
     -d "{\"device_id\": \"$DEVICE_ID\", \"helper_psk\": \"$JOIN_HELPER_PSK\"}"

# Now wait until the device is "active"
while true; do
    STATE=$(curl -s "http://localhost:17133/organizations/active/device" | jq -r '.state')
    if [ "$STATE" = "accepted" ]; then
        break
    fi
    echo "Waiting for device to become active..."
    sleep 5
done
