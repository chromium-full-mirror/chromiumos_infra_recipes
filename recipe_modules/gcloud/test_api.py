# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class GcloudApiTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the gcloud module."""

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

  def disk_list_data(self):
    """Returns list of disks in json format."""
    disk_list = [{
        "name": "staging-chromiumos-main-16285361-us-central2-c-cros"
    }, {
        "name": "chromeos-ci-infra-us-central1-b-x16-0-nvcj-cros"
    }, {
        "name": "chromeos-ci-infra-us-central1-b-x16-0-nvcj-crosr90"
    }]
    return disk_list
