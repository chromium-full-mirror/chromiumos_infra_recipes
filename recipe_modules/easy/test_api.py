# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from google.protobuf import json_format


class EasyTestApi(recipe_test_api.RecipeTestApi):
  """Simulate test data for easy api."""

  def simulate_json_step(self, step_name, data):
    return self.step_data(step_name, self.m.json.output_stream(data))

  def simulate_jsonpb_step(self, step_name, data):
    return self.step_data(
        step_name, self.m.raw_io.stream_output(json_format.MessageToJson(data)))
