# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with SSCI."""

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote as url_quote
from typing import List
from recipe_engine import step_data
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.config_types import Path
from google.protobuf.message import Message
from google.protobuf import json_format

from PB.chromite.api.sysroot import Sysroot
from PB.chromite.api.third_party_inventory import CollectPackageMetadataRequest
from PB.chromiumos.common import Chroot
from PB.chromiumos.build.api.third_party_inventory import PackageMetadata


@dataclass
class UploadedSBOM:
  digest: str
  gs_url: str

# SPDX consts.
_SPDX_DOCUMENT_ID = "SPDXRef-DOCUMENT"
_SPDX_ORGANIZATION = "Google LLC"
_SPDX_TOOL_NAME = "ChromeOS Release Recipe"


def _parse_protojson(s: str, proto_class: type[Message]) -> Message:
  """Parse a protojson `s` into a message of `proto_class`."""
  msg = proto_class()
  return json_format.Parse(s, msg, ignore_unknown_fields=True)


def _to_spdx_id(p: PackageMetadata) -> str:
  """Construct a stable SPDXID for package."""
  return f'SPDXRef-Package-{p.category}-{p.name}-{p.version}-{p.revision}'


def _to_spdx_package(p: PackageMetadata) -> dict:
  """Construct a SPDX package."""
  return {
      "SPDXID": _to_spdx_id(p),
      # Use Portage category + name to avoid name collisions.
      "name": f'{p.category}-{p.name}',
      "versionInfo": p.version,
      "description": p.description,
      "originator": "NOASSERTION",
      "supplier": f"Organization: {_SPDX_ORGANIZATION}",
      "downloadLocation": "NONE",
      "externalRefs": [{
          "referenceCategory": "OTHER",
          "referenceLocator": "NOASSERTION",
          "referenceType": "NOASSERTION"
      }],
      "filesAnalyzed": False,
  }


def _to_spdx_package_relationship(p: PackageMetadata) -> dict:
  """Construct a SPDX relationship entry of a package."""
  return {
      "spdxElementId": _SPDX_DOCUMENT_ID,
      "relatedSpdxElement": _to_spdx_id(p),
      "relationshipType": "DESCRIBES"
  }


# For now, we hardcode SPDX fields to generate a minimal SBOM.
#
# In the future, this will becomes its own tooling and ingest PackageMetadata
# protojson directly to produce a SPDX file (using SDPX tooling).
def _build_spdx_dict(name: str, unique_id: str, creation_time: datetime,
                     packages: List[PackageMetadata]) -> dict:
  """Construct a SPDX JSON file based on PackageMetadata.

  Args:
      name: A human readable name of the SPDX document
      unique_id: An unique id for constructing SPDX document namespace
      creation_time: A datatime object
      packages: A list of package metadata that should be included

  Returns:
      A dict that can be serialized into a SPDX JSON document.
  """
  spdx_dict = {
      "SPDXID": _SPDX_DOCUMENT_ID,
      "creationInfo": {
          "created":
              creation_time.isoformat(),
          "creators": [
              f"Organization: {_SPDX_ORGANIZATION}",
              f"Tool: {_SPDX_TOOL_NAME}",
          ]
      },
      "dataLicense": "CC0-1.0",
      "name": f"ChromeOS SBOM: {name}",
      "spdxVersion": "SPDX-2.3",
      "documentNamespace": f"https://spdx.google/{url_quote(unique_id)}",
      "packages": list(map(_to_spdx_package, packages)),
      "relationships": list(map(_to_spdx_package_relationship, packages)),
  }
  return spdx_dict


class CrosSsciApi(RecipeApi):
  """API for working with SSCI."""

  def generate_and_upload_sbom(self) -> UploadedSBOM:
    """Generate and upload SBOM to GCS."""
    with self.m.step.nest('generate and report SBOM'):
      name = 'baseline-sbom.spdx.json'
      local_path = self.m.path.mkdtemp('cros_ssci') / name

      self.generate_sbom(local_path)
      return self.upload_sbom(local_path, name)

  def generate_sbom(self, out_path: Path) -> step_data.StepData:
    """Generate SBOM and write SPDX JSON to out_path."""
    packages = self.collect_package_metadata(sysroot=self.m.build_menu.sysroot,
                                             chroot=self.m.build_menu.chroot)

    with self.m.step.nest('generate a baseline SBOM'):
      builder_full_name = self.m.buildbucket.builder_full_name
      build_id = self.m.buildbucket.build.id
      version = self.m.cros_version.version
      spdx_dict = _build_spdx_dict(name=f"{builder_full_name} {version}",
                                   unique_id=f'{builder_full_name}/{build_id}',
                                   creation_time=self.m.time.utcnow(),
                                   packages=packages)

    return self.m.file.write_json("write SPDX SBOM", out_path, data=spdx_dict,
                                  indent=2)

  def upload_sbom(self, local_path: Path, gs_file_name: str) -> UploadedSBOM:
    """Upload SBOM at `local_path` to GCS under this build's artifact path using `gs_file_name`.

    Returns `UploadedSBOM`, which can be passed to a later report_sbom() call.
    """
    digest = self.m.file.file_hash(local_path, test_data='feedf00d')

    config = self.m.build_menu.config_or_default
    gs_bucket = config.artifacts.artifacts_gs_bucket
    gs_path = f'{self.m.build_menu.artifacts_build_path()}/{gs_file_name}'
    self.m.gsutil.upload(source=local_path, bucket=gs_bucket, dest=gs_path)

    gs_url = f'gs://{gs_bucket}/{gs_path}'
    return UploadedSBOM(digest=digest, gs_url=gs_url)


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
