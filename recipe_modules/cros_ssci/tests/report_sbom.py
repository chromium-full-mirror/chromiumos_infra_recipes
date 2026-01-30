# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests generate_sbom and upload_sbom."""

from typing import Iterable, List
from recipe_engine import post_process
from google.protobuf import json_format

from PB.chromite.api.third_party_inventory import CollectPackageMetadataResponse
from PB.chromiumos.build.api.third_party_inventory import PackageMetadata
from PB.chromiumos import common as common_pb2
from RECIPE_MODULES.chromeos.cros_ssci.api import _BASELINE_SPDX_FILENAME, _KERNEL_SPDX_FILENAME

DEPS = [
    'build_menu',
    'cros_build_api',
    'cros_ssci',
    'test_util',
    'recipe_engine/buildbucket',
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/path',
    'recipe_engine/step',
]


def _to_build_api_protojson(packages: Iterable[PackageMetadata]) -> List[str]:
  return [json_format.MessageToJson(package) for package in packages]


def RunSteps(api):
  sboms = api.cros_ssci.generate_and_upload_sbom_for_system_images(
      sysroot=api.build_menu.sysroot, chroot=api.build_menu.chroot,
      sbom_gs_bucket='chromeos-releases-test',
      sbom_gs_path=api.build_menu.artifacts_build_path())

  api.assertions.assertRegexpMatches(
      sboms[common_pb2.IMAGE_TYPE_BASE].gs_url,
      f'gs://chromeos-releases-test/kukui-release-main/R[^/]+/{_BASELINE_SPDX_FILENAME}',
  )

  api.assertions.assertRegexpMatches(
      sboms[common_pb2.IMAGE_TYPE_FLEXOR_KERNEL].gs_url,
      f'gs://chromeos-releases-test/kukui-release-main/R[^/]+/{_KERNEL_SPDX_FILENAME}',
  )


def GenTests(api):
  yield api.test(
      'report_sbom',
      api.cros_build_api.set_api_return(
          parent_step_name=None,
          endpoint='ThirdPartyInventoryService/CollectPackageMetadata',
          data=json_format.MessageToJson(
              CollectPackageMetadataResponse(
                  success=True, metadata_protojson=_to_build_api_protojson([
                      PackageMetadata(category="sys-kernel",
                                      name="chromeos-kernel-6_6",
                                      version="6.6.99"),
                      PackageMetadata(category="category", name="package",
                                      version="1.0"),
                  ]))),
      ),
      api.test_util.test_child_build(
          'kukui',
          builder_name='kukui-release-main',
          git_repo='https://chrome-internal.googlesource.com/chromeos/manifest-internal',
      ).build,
      api.post_check(post_process.StatusSuccess),
  )
