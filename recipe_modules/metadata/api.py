# -*- coding: utf-8 -*-

# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to support metadata generation and wrangling."""

# Python imports
from collections import namedtuple
from typing import Optional

# Recipe API
from recipe_engine import recipe_api

# Protobuffer imports
from PB.chromite.api.artifacts import FetchMetadataRequest
from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.build.api.container_metadata import ContainerMetadata
from PB.chromiumos.common import Chroot
from PB.chromiumos.test.api.test_case import TestCase
from PB.chromiumos.test.api.test_case_metadata import TestCaseMetadata
from PB.chromiumos.test.api.test_case_metadata import TestCaseMetadataList
from PB.go.chromium.org.luci.resultdb.proto.v1.invocation import Sources


class MetadataApi(recipe_api.RecipeApi):
  """A module with config and support methods for metadata.

  Specifically, this supports the new class of metadata we're generating
  as part of a build, including, but not necessarily limited to:
    * container metadata
    * software metadata
    * hardware metadata
    * test metadata
  """

  def __init__(self, props, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.sources_gitiles_commit_override = props.sources_gitiles_commit_override

  class MetadataInfo(
      namedtuple('MetadataType', ['name', 'filename', 'msgtype'])):
    """Tuple to specify info about a supported metadata payload.

    Args:
      name (str): Human readable name for metadata (eg: 'container')
      filename (str): Canonical filename for the metadata payload
      msgtype (type): Reference to the protobuffer message type for metadata
    """

  # Folder in a build's GS path to put metadata
  METADATA_GSDIR = 'metadata'

  # Define supported metadata types
  CONTAINER_METADATA_INFO = \
      MetadataInfo('container', 'containers.jsonpb', ContainerMetadata)

  SOURCES_METADATA_INFO = \
      MetadataInfo('sources', 'sources.jsonpb', Sources)

  METADATA_PAYLOADS = {
      'container': CONTAINER_METADATA_INFO,
  }

  # TestCaseMetadataList to use when testing fetch_test_metadata.
  EXAMPLE_TEST_METADATA_LIST = TestCaseMetadataList(
      values=[TestCaseMetadata(test_case=TestCase(name='example_test'))])

  def gspath(self, metadata_info, gs_bucket=None, gs_path=None):
    """Return full or relative path to a metadata payload
    depending on if bucket info is provided or not.

    Args:
      metadata_info (MetadataInfo): Metadata config information
      gs_bucket (str): optional gs bucket
      gs_path (str): optional gs path

    Returns:
      The relative GCS path for metadata if gs_bucket, gs_path not provided.
      Otherwise, returns the full GCS path to metadata.
    """
    if not gs_bucket and not gs_path:
      return self.m.path.join(
          MetadataApi.METADATA_GSDIR,
          metadata_info.filename,
      )

    full_gcs_path = self.m.path.join(
        gs_bucket,
        gs_path,
        MetadataApi.METADATA_GSDIR,
        metadata_info.filename,
    )

    # Force path to have a gs:// prefix.
    prefix = '' if full_gcs_path.startswith('gs://') else 'gs://'
    return '{}{}'.format(prefix, full_gcs_path)

  def fetch_test_metadata(
      self,
      chroot: Chroot,
      sysroot: Sysroot,
      mock_metadata_file: bool = True,
  ) -> Optional[TestCaseMetadataList]:
    """Fetch and return test case metadata.

    Args:
      chroot: proto representing the chroot
      sysroot: proto representing the sysroot
      mock_metadata_file: boolean which should always be true unless
        testing the case when a metadata file is not found

    Returns:
      A TestCaseMetadataList containing the metadata of all tests, or None
      if the ArtifactsService/FetchMetadata endpoint is unavailable or all
      metadata files are empty.
    """
    if not self.m.cros_build_api.has_endpoint(
        self.m.cros_build_api.ArtifactsService, 'FetchMetadata'):
      return None
    response = self.m.cros_build_api.ArtifactsService.FetchMetadata(
        FetchMetadataRequest(chroot=chroot, sysroot=sysroot))

    # Combine multiple files each containing a TestCaseMetadataList.
    test_metadata = TestCaseMetadataList()
    for result_path in response.filepaths:
      recipes_path = self.m.util.proto_path_to_recipes_path(
          proto_path=result_path.path)
      if mock_metadata_file:
        self.m.path.mock_add_file(recipes_path)
      if self.m.path.exists(recipes_path):
        contents = self.m.file.read_raw(
            name=f'read {recipes_path}',
            source=recipes_path,
            test_data=self.EXAMPLE_TEST_METADATA_LIST.SerializeToString(),
        )
        test_metadata.MergeFromString(contents)
    if len(test_metadata.values) == 0:
      return None

    return test_metadata
