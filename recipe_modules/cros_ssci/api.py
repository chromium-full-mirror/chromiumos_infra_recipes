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
from PB.chromiumos import common as common_pb2
from PB.chromiumos.build.api.third_party_inventory import PackageMetadata


@dataclass
class UploadedSBOM:
  digest: str
  gs_url: str

# SPDX consts.
_SPDX_DOCUMENT_ID = "SPDXRef-DOCUMENT"
_SPDX_PACKAGE_MAIN_ID = "SPDXRef-Package-main"
_SPDX_ORGANIZATION = "Google LLC"

# SPDX creator tool identifier (by convention).
#  - Tool name shouldn't contain dash ("-")
#  - Tool version is a monotonically increasing number
_SPDX_TOOL_NAME = "ChromeOsReleaseRecipe"
_SPDX_TOOL_VERSION = "1"

_BASELINE_SPDX_FILENAME = 'baseline-sbom.spdx.json'
_KERNEL_SPDX_FILENAME = 'kernel-sbom.spdx.json'


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
      "licenseConcluded": "NOASSERTION",
      "licenseDeclared": "NOASSERTION",
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
      "spdxElementId": _SPDX_PACKAGE_MAIN_ID,
      "relatedSpdxElement": _to_spdx_id(p),
      "relationshipType": "CONTAINS"
  }


def _build_main_package(name: str, version: str) -> dict:
  """Construct a main package dict."""
  return {
      "name": name,
      "SPDXID": _SPDX_PACKAGE_MAIN_ID,
      "versionInfo": version,
      "supplier": f"Organization: {_SPDX_ORGANIZATION}",
      "downloadLocation": "https://www.google.com/",
      "filesAnalyzed": False,
      "licenseConcluded": "NOASSERTION",
      "licenseDeclared": "NOASSERTION"
  }


# For now, we hardcode SPDX fields to generate a minimal SBOM.
#
# In the future, this may become its own tooling and ingest PackageMetadata
# protojson directly to produce a SPDX file (using SDPX tooling).
def _build_spdx_dict(name: str, unique_id: str, creation_time: datetime,
                     packages: List[PackageMetadata],
                     main_package: dict[str, str]) -> dict:
  """Construct a SPDX JSON file based on PackageMetadata.

  Args:
      name: A human readable name of the SPDX document
      unique_id: An unique id for constructing SPDX document namespace
      creation_time: A datatime object
      packages: A list of package metadata that should be included
      main_package: A SPDX package dict that serves as the "main" package
          of this SPDX document. This should be constructed to reflect the
          built system image (e.g. version, etc)
  Returns:
      A dict that can be serialized into a SPDX JSON document.
  """

  spdx_packages = [main_package, *map(_to_spdx_package, packages)]
  spdx_relationships = [
      # Document describes the main package.
      {
          "spdxElementId": "SPDXRef-DOCUMENT",
          "relatedSpdxElement": "SPDXRef-Package-main",
          "relationshipType": "DESCRIBES"
      },
      # Main package contains other packages.
      *list(map(_to_spdx_package_relationship, packages)),
  ]

  spdx_dict = {
      "SPDXID": _SPDX_DOCUMENT_ID,
      "creationInfo": {
          # Add timezone suffix to be fully compliant with ISO-8601.
          "created":
              creation_time.isoformat() + 'Z',
          "creators": [
              f"Organization: {_SPDX_ORGANIZATION}",
              f"Tool: {_SPDX_TOOL_NAME}-{_SPDX_TOOL_VERSION}",
          ]
      },
      "dataLicense": "CC0-1.0",
      "name": name,
      "spdxVersion": "SPDX-2.3",
      "documentNamespace": f"https://spdx.google/{url_quote(unique_id)}",
      "packages": spdx_packages,
      "relationships": spdx_relationships,
  }
  return spdx_dict


class CrosSsciApi(RecipeApi):
  """API for working with SSCI."""

  def generate_and_upload_sbom_for_system_images(
      self, sysroot: Sysroot, chroot: Chroot, sbom_gs_bucket: str,
      sbom_gs_path: str) -> dict[common_pb2.ImageType, UploadedSBOM]:
    """Generate and upload SBOM to GCS.

    This generates both baseline and kernel SBOMs from the same package metadata.

    Args:
      sysroot: Sysroot protobuf.
      chroot: Chroot protobuf.
      sbom_gs_bucket: GCS bucket to upload to.
      sbom_gs_path: GCS path prefix to upload to.

    Returns:
      A dict mapping common_pb2.ImageType to UploadedSBOM.
    """
    packages = self.collect_package_metadata(sysroot=sysroot, chroot=chroot)

    builder_full_name = self.m.buildbucket.builder_full_name
    build_id = self.m.buildbucket.build.id
    version_str = str(self.m.cros_version.version)

    tempdir = self.m.path.mkdtemp('cros_ssci')
    result = {}

    with self.m.step.nest('generate and upload baseline SBOM'):
      spdx_dict = _build_spdx_dict(
          name=f"ChromeOS System Image SBOM: {version_str}",
          unique_id=f'{builder_full_name}/{build_id}',
          creation_time=self.m.time.utcnow(),
          packages=packages,
          main_package=_build_main_package(
              name="ChromeOS System Image",
              version=version_str,
          ),
      )

      local_path = tempdir / _BASELINE_SPDX_FILENAME
      self.m.file.write_json("write SPDX SBOM", local_path, data=spdx_dict,
                             indent=2)
      uploaded_sbom = self.upload_sbom(
          local_path, gs_bucket=sbom_gs_bucket,
          gs_path=f'{sbom_gs_path}/{_BASELINE_SPDX_FILENAME}')

      for image_type in [
          common_pb2.IMAGE_TYPE_BASE, common_pb2.IMAGE_TYPE_RECOVERY,
          common_pb2.IMAGE_TYPE_FACTORY, common_pb2.IMAGE_TYPE_TEST
      ]:
        result[image_type] = uploaded_sbom

    with self.m.step.nest('generate and upload kernel SBOM'):
      # A predicate that picks packages that forms the standalone kernel.
      package_filter = lambda package: (
          package.category == 'sys-kernel' and package.name.startswith(
              "chromeos-kernel"))
      kernel_packages = list(filter(package_filter, packages))

      spdx_dict = _build_spdx_dict(
          name=f"ChromeOS Kernel SBOM: {builder_full_name} {version_str}",
          unique_id=f'{builder_full_name}/{build_id}',
          creation_time=self.m.time.utcnow(),
          packages=kernel_packages,
          main_package=_build_main_package(
              name=f"ChromeOS_Kernel_{builder_full_name}",
              version=version_str,
          ),
      )

      local_path = tempdir / _KERNEL_SPDX_FILENAME
      self.m.file.write_json("write SPDX SBOM", local_path, data=spdx_dict,
                             indent=2)
      uploaded_sbom = self.upload_sbom(
          local_path, gs_bucket=sbom_gs_bucket,
          gs_path=f'{sbom_gs_path}/{_KERNEL_SPDX_FILENAME}')
      result[common_pb2.IMAGE_TYPE_FLEXOR_KERNEL] = uploaded_sbom

    return result


  def generate_dlc_sbom(self, dlc_name: str,
                        out_path: Path) -> step_data.StepData:
    """Generate DLC SBOM and write SPDX JSON to out_path.

    Args:
      dlc_name: Name of the DLC (this will be the SPDX package name)
      out_path: Path to write the SPDX JSON to.

    The generated DLC SBOM is a stub:
      - The result SPDX contains exactly one main package
      - The main package is derived from `dlc_name`
      - Versioning info are derived from buildbucket

    Each OS image always maps to one set of DLCs. The DLC's binary content might
    be the same for multiple OS versions / boards.
    """
    with self.m.step.nest('generate DLC SBOM'):
      builder_full_name = self.m.buildbucket.builder_full_name
      build_id = self.m.buildbucket.build.id
      version = self.m.cros_version.version

      spdx_dict = _build_spdx_dict(
          name=f"ChromeOS DLC SBOM: {dlc_name}",
          unique_id=f'{builder_full_name}/{build_id}/dlc/{dlc_name}',
          creation_time=self.m.time.utcnow(),
          packages=[],
          main_package=_build_main_package(
              name=f"ChromeOS_DLC_{dlc_name}",
              version=str(version),
          ),
      )

      return self.m.file.write_json("write DLC SPDX SBOM", out_path,
                                    data=spdx_dict, indent=2)

  def upload_sbom(self, local_path: Path, gs_bucket: str,
                  gs_path: str) -> UploadedSBOM:
    """Upload SBOM at `local_path` to GCS under this build's artifact path using `gs_file_name`.

    Returns `UploadedSBOM`, which can be passed to a later report_sbom() call.
    """
    digest = self.m.file.file_hash(local_path, test_data='feedf00d')
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
