# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests collect_package_metadata call."""

from typing import Iterable, List
from recipe_engine import post_process
from google.protobuf import json_format

from PB.chromite.api import sysroot as sysroot_pb2
from PB.chromite.api.third_party_inventory import CollectPackageMetadataResponse
from PB.chromiumos.build.api.third_party_inventory import PackageMetadata
from PB.chromiumos import common as common_pb2

DEPS = [
    'cros_build_api',
    'cros_ssci',
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
]


def _to_build_api_protojson(packages: Iterable[PackageMetadata]) -> List[str]:
  return [json_format.MessageToJson(package) for package in packages]


def RunSteps(api):
  with api.step.nest('collect from test data'):
    packages = api.cros_ssci.collect_package_metadata(
        chroot=common_pb2.Chroot(path='/path/to/chroot'),
        sysroot=sysroot_pb2.Sysroot(path='/path/to/sysroot'),
    )
    api.assertions.assertEqual(
        sorted([f'{package.category}/{package.name}' for package in packages]),
        sorted(['app-shells/bash', 'app-shells/zsh']),
    )


def GenTests(api):
  yield api.test(
      'collect from test data',
      api.cros_build_api.set_api_return(
          parent_step_name='collect from test data',
          endpoint='ThirdPartyInventoryService/CollectPackageMetadata',
          data=json_format.MessageToJson(
              CollectPackageMetadataResponse(
                  success=True, metadata_protojson=_to_build_api_protojson([
                      PackageMetadata(category="app-shells", name="bash",
                                      version="1.0.0_p2"),
                      PackageMetadata(category="app-shells", name="zsh",
                                      version="2.0.0_p1"),
                  ]))),
      ),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
