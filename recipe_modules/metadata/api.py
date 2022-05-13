# -*- coding: utf-8 -*-

# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to support metadata generation and wrangling."""

# Python imports
from collections import namedtuple

# Recipe API
from recipe_engine import recipe_api

# Protobuffer imports
from PB.chromiumos.build.api.container_metadata import ContainerMetadata


class MetadataApi(recipe_api.RecipeApi):
  """A module with config and support methods for metadata.

  Specifically, this supports the new class of metadata we're generating
  as part of a build, including, but not necessarily limited to:
    * container metadata
    * software metadata
    * hardware metadata
    * test metadata
  """

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

  # Define suported metadata types
  CONTAINER_METADATA_INFO = \
      MetadataInfo('container', 'containers.jsonpb', ContainerMetadata)

  METADATA_PAYLOADS = {
      'container': CONTAINER_METADATA_INFO,
  }

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
