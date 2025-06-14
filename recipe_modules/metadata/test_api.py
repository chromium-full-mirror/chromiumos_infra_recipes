# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

# Protobuffer imports
from PB.chromiumos.build.api import container_metadata


class MetadataTestApi(recipe_test_api.RecipeTestApi):
  """Test examples for metadata api."""

  def mock_metadata(self, target='test-target'):
    metadata = container_metadata.ContainerMetadata(
        containers={
            target:
                container_metadata.ContainerImageMap(
                    images={
                        'cros-test':
                            container_metadata.ContainerImageInfo(
                                repository=container_metadata.GcrRepository(
                                    hostname='gcr.io',
                                    project='chromeos-bot',
                                ),
                                name='cros-test',
                                digest='sha256:3e36d3622f5adad01080cc2120bb72c0714ecec6118eb9523586410b7435ae80',
                                tags=[
                                    '8835841547076258945',
                                    'amd64-generic-release.R96-1.2.3',
                                ],
                            ),
                    }),
        })
    return metadata
