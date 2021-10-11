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

  def snapshot_list_data(self):
    """Returns list of snapshots in json format."""
    snapshot_list = [{
        "creationTimestamp":
            "2021-07-09T20:12:11.796-07:00",
        "diskSizeGb":
            "200",
        "downloadBytes":
            "78986442536",
        "id":
            "7781563162436087524",
        "kind":
            "compute#snapshot",
        "labelFingerprint":
            "42WmSpB8rSM=",
        "name":
            "staging-chrome-cache-snapshot-16258867",
        "selfLink":
            "https://www.googleapis.com/compute/v1/projects/chromeos-bot/global/snapshots/staging-chrome-cache-snapshot-16258867",
        "sourceDisk":
            "https://www.googleapis.com/compute/v1/projects/chromeos-bot/zones/us-central2-c/disks/staging-source-cache-disk-chrome-us-central2-c",
        "sourceDiskId":
            "4287499025374294961",
        "status":
            "READY",
        "storageBytes":
            "78985626944",
        "storageBytesStatus":
            "UP_TO_DATE",
        "storageLocations": ["us"]
    }, {
        "creationTimestamp":
            "2021-07-09T21:11:05.550-07:00",
        "diskSizeGb":
            "200",
        "downloadBytes":
            "78994231357",
        "id":
            "4736713593347941175",
        "kind":
            "compute#snapshot",
        "labelFingerprint":
            "42WmSpB8rSM=",
        "name":
            "staging-chromeos-cache-snapshot-16258902",
        "selfLink":
            "https://www.googleapis.com/compute/v1/projects/chromeos-bot/global/snapshots/staging-chromeos-cache-snapshot-16258902",
        "sourceDisk":
            "https://www.googleapis.com/compute/v1/projects/chromeos-bot/zones/us-east1-d/disks/staging-source-cache-disk-chromeos-us-east1-d",
        "sourceDiskId":
            "2341635010697930119",
        "status":
            "READY",
        "storageBytes":
            "78993415936",
        "storageBytesStatus":
            "UP_TO_DATE",
        "storageLocations": ["us"]
    }, {
        "creationTimestamp":
            "2021-07-09T22:12:18.806-07:00",
        "diskSizeGb":
            "200",
        "downloadBytes":
            "78999426485",
        "id":
            "4629036345170629341",
        "kind":
            "compute#snapshot",
        "labelFingerprint":
            "42WmSpB8rSM=",
        "name":
            "staging-chromeos-cache-snapshot-16258939",
        "selfLink":
            "https://www.googleapis.com/compute/v1/projects/chromeos-bot/global/snapshots/staging-chromeos-cache-snapshot-16258939",
        "sourceDisk":
            "https://www.googleapis.com/compute/v1/projects/chromeos-bot/zones/us-east1-d/disks/staging-source-cache-disk-chromeos-us-east1-d",
        "sourceDiskId":
            "5316746804958893913",
        "status":
            "READY",
        "storageBytes":
            "78998610816",
        "storageBytesStatus":
            "UP_TO_DATE",
        "storageLocations": ["us"]
    }]
    return snapshot_list

  def snapshot_exists_data(self):
    """Returns list of snapshots in json format."""
    snapshot_list = [{
        "name": "chromiumos-main-16287984"
    }, {
        "name": "staging-chromiumos-release-r93-14092-b-16287710"
    }, {
        "name": "chrome-release-r93-14092-b-16287710"
    }, {
        "name": "test-cache-snapshot-123",
    }]
    return snapshot_list

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

  def disk_attached_data(self):
    """Returns dict of disks in json format."""
    disk_dict = {
        'disks': [{
            "source":
                "https://www.googleapis.com/compute/v1/projects/chromeos-bot/zones/us-east1-d/disks/chromeos-ci-infra-us-central1-b-x16-0-nvcj-cros"
        }, {
            "source":
                "https://www.googleapis.com/compute/v1/projects/chromeos-bot/zones/us-east1-d/disks/chromeos-ci-infra-us-central1-b-x16-0-nvcj-cr"
        }, {
            "source":
                "https://www.googleapis.com/compute/v1/projects/chromeos-bot/zones/us-east1-d/disks/chromeos-ci-infra-us-central1-b-x16-0-disk-crosr90"
        }]
    }
    return disk_dict

  def blkid_test_data(self):
    """Returns dict of local disks in json format."""
    blkid_dict = {
        "blockdevices": [{
            "name": "loop0"
        }, {
            "name": "loop1"
        }, {
            "name": "loop2"
        }, {
            "name": "loop3"
        }, {
            "name": "loop4"
        }, {
            "name": "loop5"
        }, {
            "name": "sda",
            "children": [{
                "name": "sda1"
            }, {
                "name": "sda14"
            }, {
                "name": "sda15"
            }]
        }, {
            "name": "sdb"
        }]
    }
    return blkid_dict

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

  @recipe_test_api.mod_test_data
  @staticmethod
  def infra_host(value):
    return value
