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
      MetadataInfo('container', 'container.jsonpb', ContainerMetadata)

  METADATA_INFOS = {
      'container': CONTAINER_METADATA_INFO,
  }
