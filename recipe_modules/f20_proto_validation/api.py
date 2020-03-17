# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A sample module to validate F20 metadata definitions.

F20 metadata definitions are not yet used from any recipes.
This recipe module ensures that the protobuf definitions continue
to be usable from the infra recipe code while F20 is in early stages.

TODO(crbug.com/1062307): Delete this recipe module once a real recipe
exists to generalize cros_test_platform a la F20.
"""

from recipe_engine import recipe_api
from google.protobuf import json_format

from PB.test.metadata.v1.metadata import Metadata, Test
from PB.test.metadata.v1.remote_test_driver import RemoteTestDriver
from PB.test.plan.v1.plan import Plan, TestCondition, Unit


class F20ProtoValidationAPI(recipe_api.RecipeApi):
  """A sample module to validate F20 metadata definitions."""

  def log_sample_metadata(self):
    """Log a sample Metadata instance."""
    self._log_to_nested_step(
        'metadata',
        json_format.MessageToJson(
            Metadata(
                remote_test_driver=RemoteTestDriver(
                    id=RemoteTestDriver.TAUTO,
                    command='echo hello world',
                ), test=[Test(name='footest')])))

  def log_sample_plan(self):
    """Log a sample Plan instance."""
    self._log_to_nested_step(
        'plan',
        json_format.MessageToJson(
            Plan(
                name='fooplan',
                units=[Unit(
                    test_condition=TestCondition(
                        expression="true",
                    ),
                )],
            )))

  def _log_to_nested_step(self, tag, json):
    with self.m.step.nest(tag) as step:
      step.logs['serialized F20 data'] = [json]
