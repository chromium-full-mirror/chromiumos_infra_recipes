# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with SSCI."""

from typing import List
from recipe_engine.recipe_api import RecipeApi
from google.protobuf.message import Message
from google.protobuf import json_format

from PB.chromite.api.sysroot import Sysroot
from PB.chromite.api.third_party_inventory import CollectPackageMetadataRequest
from PB.chromiumos.common import Chroot
from PB.chromiumos.build.api.third_party_inventory import PackageMetadata


def _parse_protojson(s: str, proto_class: type[Message]) -> Message:
  """Parse a protojson `s` into a message of `proto_class`."""
  msg = proto_class()
  return json_format.Parse(s, msg, ignore_unknown_fields=True)


class CrosSsciApi(RecipeApi):
  """API for working with SSCI."""

  def collect_package_metadata(self, chroot: Chroot,
                               sysroot: Sysroot) -> List[PackageMetadata]:
    """Collects metadata about installed packages in sysroot.

    Args:
      chroot: The chroot where the sysroot is.
      sysroot: The sysroot to collect package metadata from.

    Returns:
      A list of strings, where each string is a JSON representation of a
      package's metadata.
    """
    req = CollectPackageMetadataRequest(
        chroot=chroot,
        sysroot=sysroot,
    )
    resp = self.m.cros_build_api.ThirdPartyInventoryService.CollectPackageMetadata(
        req,
    )

    return [
        _parse_protojson(protojson, PackageMetadata)
        for protojson in resp.metadata_protojson
    ]
