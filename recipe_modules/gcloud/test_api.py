# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class GcloudApiTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the gcloud module."""

  def instances_data(self):
    """Returns list of instances in json format."""
    disk_list = [{
        "name":
            "chromeos-ci-infra-us-central1-b-x16-0-nvcj",
        "zone":
            "https://www.googleapis.com/compute/v1/projects/chromeos-bot/zones/us-central1-b",
    }, {
        "name":
            "chromeos-ci-infra-us-central1-b-x16-0-disk",
        "zone":
            "https://www.googleapis.com/compute/v1/projects/chromeos-bot/zones/us-central1-b",
    }]
    return disk_list

  def image_exists_data(self):
    """Returns list of images in json format."""
    image_list = [{
        "name": "chromiumos-main-16287984"
    }, {
        "name": "staging-chromiumos-release-r93-14092-b-16287710"
    }, {
        "name": "chrome-release-r93-14092-b-16287710"
    }, {
        "name": "test-cache-snapshot-123",
    }]
    return image_list

  def disk_exists_data(self, disk):
    """Returns list of disks in json format."""
    if disk.startswith('chrome-'):
      return {}
    return {"name": disk}

  def disk_list_data(self):
    """Returns list of disks in json format."""
    disk_list = [{
        "name":
            "chromeos-ci-infra-us-central1-b-x16-0-lmno",
        "zone":
            "https://www.googleapis.com/compute/v1/projects/chromeos-bot/zones/us-central1-b",
    }, {
        "name":
            "chromeos-ci-infra-us-central1-b-x16-0-lmno-cros",
        "zone":
            "https://www.googleapis.com/compute/v1/projects/chromeos-bot/zones/us-central1-b",
    }, {
        "name":
            "chromeos-ci-infra-us-central1-b-x16-0-nvcj-cros",
        "zone":
            "https://www.googleapis.com/compute/v1/projects/chromeos-bot/zones/us-central1-b",
    }, {
        "name":
            "chromeos-ci-infra-us-central1-b-x16-0-nvcj-cr",
        "zone":
            "https://www.googleapis.com/compute/v1/projects/chromeos-bot/zones/us-central1-b",
    }, {
        "name":
            "chromeos-ci-infra-us-central1-b-x16-0-disk-crosr90",
        "zone":
            "https://www.googleapis.com/compute/v1/projects/chromeos-bot/zones/us-central1-b",
    }, {
        "name":
            "chromeos-ci-infra-us-central1-b-x16-0-disk-cros",
        "zone":
            "https://www.googleapis.com/compute/v1/projects/chromeos-bot/zones/us-central1-b",
    }]
    return disk_list

  def images_list_data(self):
    """Returns a list of images in json format."""
    images_list = [{
        "archiveSizeBytes":
            "84563945856",
        "creationTimestamp":
            "2021-07-09T22:12:18.806-07:00",
        "diskSizeGb":
            "150",
        "guestOsFeatures": [{
            "type": "SEV_CAPABLE"
        }, {
            "type": "VIRTIO_SCSI_MULTIQUEUE"
        }, {
            "type": "UEFI_COMPATIBLE"
        }],
        "id":
            "285866261851149625",
        "kind":
            "compute#image",
        "labelFingerprint":
            "42WmSpB8rSM=",
        "licenseCodes": ["5926592092274602096", "1002001"],
        "licenses": [
            "https://www.googleapis.com/compute/v1/projects/ubuntu-os-cloud/global/licenses/ubuntu-1804-lts",
            "https://www.googleapis.com/compute/v1/projects/vm-options/global/licenses/enable-vmx"
        ],
        "name":
            "staging-chromeos-cache-snapshot-16258939",
        "selfLink":
            "https://www.googleapis.com/compute/v1/projects/chromeos-bot/global/images/chromeos-bionic-21030700-6937fbe1116",
        "sourceDisk":
            "https://www.googleapis.com/compute/v1/projects/chromeos-bot/zones/us-central1-b/disks/proto-chromeos-bionic",
        "sourceDiskId":
            "2312027915646714963",
        "sourceType":
            "RAW",
        "status":
            "READY",
        "storageLocations": ["us"]
    }, {
        "archiveSizeBytes":
            "108697230208",
        "creationTimestamp":
            "2021-07-09T22:12:18.806-07:00",
        "diskSizeGb":
            "200",
        "guestOsFeatures": [{
            "type": "VIRTIO_SCSI_MULTIQUEUE"
        }, {
            "type": "SEV_CAPABLE"
        }, {
            "type": "UEFI_COMPATIBLE"
        }],
        "id":
            "3774636035690476222",
        "kind":
            "compute#image",
        "labelFingerprint":
            "42WmSpB8rSM=",
        "licenseCodes": ["5926592092274602096", "1002001"],
        "licenses": [
            "https://www.googleapis.com/compute/v1/projects/ubuntu-os-cloud/global/licenses/ubuntu-1804-lts",
            "https://www.googleapis.com/compute/v1/projects/vm-options/global/licenses/enable-vmx"
        ],
        "name":
            "staging-chromeos-cache-snapshot-16258902",
        "selfLink":
            "https://www.googleapis.com/compute/v1/projects/chromeos-bot/global/images/chromeos-bionic-21081200-6dc0a9d8240",
        "sourceDisk":
            "https://www.googleapis.com/compute/v1/projects/chromeos-bot/zones/us-central1-b/disks/proto-chromeos-bionic",
        "sourceDiskId":
            "2984261989078459033",
        "sourceType":
            "RAW",
        "status":
            "READY",
        "storageLocations": ["us"]
    }, {
        "archiveSizeBytes":
            "108697230208",
        "creationTimestamp":
            "2021-07-09T22:12:18.806-07:00",
        "diskSizeGb":
            "200",
        "guestOsFeatures": [{
            "type": "VIRTIO_SCSI_MULTIQUEUE"
        }, {
            "type": "SEV_CAPABLE"
        }, {
            "type": "UEFI_COMPATIBLE"
        }],
        "id":
            "3774636035690476222",
        "kind":
            "compute#image",
        "labelFingerprint":
            "42WmSpB8rSM=",
        "licenseCodes": ["5926592092274602096", "1002001"],
        "licenses": [
            "https://www.googleapis.com/compute/v1/projects/ubuntu-os-cloud/global/licenses/ubuntu-1804-lts",
            "https://www.googleapis.com/compute/v1/projects/vm-options/global/licenses/enable-vmx"
        ],
        "name":
            "staging-chrome-cache-snapshot-16258867",
        "selfLink":
            "https://www.googleapis.com/compute/v1/projects/chromeos-bot/global/images/chromeos-bionic-21081200-6dc0a9d8240",
        "sourceDisk":
            "https://www.googleapis.com/compute/v1/projects/chromeos-bot/zones/us-central1-b/disks/proto-chromeos-bionic",
        "sourceDiskId":
            "2984261989078459033",
        "sourceType":
            "RAW",
        "status":
            "READY",
        "storageLocations": ["us"]
    }]
    return images_list

  def instance_data(self):
    """Returns metadata of a single instance in json format."""
    metadata = [{
        "canIpForward":
            False,
        "cpuPlatform":
            "Intel Cascade Lake",
        "creationTimestamp":
            "2021-10-20T22:58:08.883-07:00",
        "deletionProtection":
            False,
        "disks": [{
            "autoDelete":
                True,
            "boot":
                True,
            "deviceName":
                "persistent-disk-0",
            "diskSizeGb":
                "17",
            "index":
                0,
            "interface":
                "SCSI",
            "kind":
                "compute#attachedDisk",
            "licenses": [
                "https://www.googleapis.com/compute/v1/projects/vm-options/global/licenses/enable-vmx"
            ],
            "mode":
                "READ_WRITE",
            "source":
                "https://www.googleapis.com/compute/v1/projects/chromeos-gce-tests/zones/us-central1-a/disks/betty-arc-r-3447702",
            "type":
                "PERSISTENT"
        }],
        "fingerprint":
            "96TqUn4aIDM=",
        "id":
            "4143780481849933727",
        "kind":
            "compute#instance",
        "labelFingerprint":
            "42WmSpB8rSM=",
        "lastStartTimestamp":
            "2021-10-20T22:58:22.786-07:00",
        "machineType":
            "https://www.googleapis.com/compute/v1/projects/chromeos-gce-tests/zones/us-central1-a/machineTypes/n2-standard-8",
        "metadata": {
            "fingerprint": "rNGahkL14fg=",
            "kind": "compute#metadata"
        },
        "name":
            "betty-arc-r-3447702",
        "networkInterfaces": [{
            "fingerprint":
                "U3oPE5xhuUo=",
            "kind":
                "compute#networkInterface",
            "name":
                "nic0",
            "network":
                "https://www.googleapis.com/compute/v1/projects/chromeos-gce-tests/global/networks/chromeos-gce-tests",
            "networkIP":
                "172.16.0.15",
            "stackType":
                "IPV4_ONLY",
            "subnetwork":
                "https://www.googleapis.com/compute/v1/projects/chromeos-gce-tests/regions/us-central1/subnetworks/us-central1"
        }],
        "scheduling": {
            "automaticRestart": True,
            "onHostMaintenance": "MIGRATE",
            "preemptible": False
        },
        "selfLink":
            "https://www.googleapis.com/compute/v1/projects/chromeos-gce-tests/zones/us-central1-a/instances/betty-arc-r-3447702",
        "startRestricted":
            False,
        "status":
            "RUNNING",
        "tags": {
            "fingerprint": "42WmSpB8rSM="
        },
        "zone":
            "https://www.googleapis.com/compute/v1/projects/chromeos-gce-tests/zones/us-central1-a"
    }]
    return metadata

  @recipe_test_api.mod_test_data
  @staticmethod
  def infra_host(value):
    return value

  @recipe_test_api.mod_test_data
  @staticmethod
  def is_mount(value):
    """Whether to assume the disk is mounted when testing."""
    return value
