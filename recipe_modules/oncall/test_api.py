# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class OncallTestApi(recipe_test_api.RecipeTestApi):
  """Test examples for test_plan api."""

  def status(self, step_name, rotation=None, primary=None, secondary=None,
             tertiary=None):
    rotation = rotation or 'chromeos-ci-eng'
    primary = primary or 'foo'
    secondary = secondary or 'bar'
    tertiary = tertiary or 'baz'
    json = [{
        'next': [secondary, 1],
        'person': primary,
        'position': 1,
        'rotation': rotation,
        'until': 2
    },
            {
                'next': [tertiary, 3],
                'person': secondary,
                'position': 2,
                'rotation': rotation,
                'until': 3,
            }]
    return self.status_json(step_name, json)

  def status_json(self, step_name, json):
    return self.m.url.json(step_name + '.fetch rotation status json', json)
