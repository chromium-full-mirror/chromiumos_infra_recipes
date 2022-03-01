# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from PB.recipe_modules.chromeos.cros_tool_runner.cros_tool_runner import \
  CrosToolRunnerProperties
from PB.recipe_modules.chromeos.cros_tool_runner.cros_tool_runner import \
  CrosToolRunnerEnvProperties
from PB.chromiumos.build.api import container_metadata


class CrosToolRunnerTestApi(recipe_test_api.RecipeTestApi):
  """Test data for CrosToolRunner api."""

  def properties(self, dut_name=None):
    """Gets properties to pass to api.test().

    For use in recipes and modules using cros_tool_runner.
    """
    if not dut_name:  # pragma: nocover
      dut_name = 'placeholder-dut-name'
    return self.m.properties(
        **{
            '$chromeos/cros_tool_runner':
                CrosToolRunnerProperties(
                    version=CrosToolRunnerProperties.Version(
                        cipd_label='some-cipd-label',
                    ), container_metadata=container_metadata.ContainerMetadata(
                        containers={
                            "test-target":
                                container_metadata.ContainerImageMap(
                                    images={
                                        'cros-test':
                                            container_metadata
                                            .ContainerImageInfo(
                                                repository=container_metadata
                                                .GcrRepository(
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
                        }))
        }) + self.m.properties.environ(
            CrosToolRunnerEnvProperties(SWARMING_BOT_ID='crossk-' + dut_name,
                                        SWARMING_TASK_ID='placeholder-task-id',
                                        SKYLAB_DUT_ID='placeholder-dut-id'))
