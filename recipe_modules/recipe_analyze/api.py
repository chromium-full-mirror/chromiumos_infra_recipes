# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for calling 'recipes.py analyze'"""

import json

from google.protobuf import json_format as jsonpb
from PB.recipe_engine import analyze as analyze_pb
from recipe_engine.recipe_api import RecipeApi, StepFailure


class RecipeAnalyzeApi(RecipeApi):
  """A module for calling 'recipes.py analyze'"""

  def is_recipe_affected(self, affected_files, recipe):
    """Return True iff changes in <affected_files> affect <recipe>.

    Must be called from the root of a recipes repo (i.e. recipes.py is in the
    cwd).

    Args:
      * affected_files (list[str]): A list of changed files. Paths may be
        absolute or relative (to the root of the recipes repo), and should use
        forward slashes only.
      * recipe (str): The name of the recipe to analyze.

    Return:
      Bool
    """
    analyze_input = {
        'files': affected_files,
        'recipes': [recipe],
    }
    step_data = self.m.step(
        'recipe analyze', [
            './recipes.py', 'analyze',
            self.m.json.input(analyze_input),
            self.m.json.output()
        ], step_test_data=lambda: self.m.json.test_api.output(
            {'recipes': ['recipeA', 'recipeB']}))

    step_data.presentation.logs['input.json'] = [json.dumps(analyze_input)]

    output_pb = jsonpb.ParseDict(
        step_data.json.output,
        analyze_pb.Output(),
    )

    if output_pb.invalid_recipes:
      # TODO(b/217973414): Remove invalid_recipes_str which is only needed
      # to ensure py2 and py3 emit the same expectations for unicode strings
      # within other data structures.
      invalid_recipes_str = '\', \''.join(output_pb.invalid_recipes)
      raise StepFailure(
          'recipes analyze failed with invalid recipes: [\'{}\']'.format(
              invalid_recipes_str))

    if output_pb.error:
      raise StepFailure('recipes analyze failed with error: {}'.format(
          output_pb.error))

    return recipe in output_pb.recipes
