# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for calling 'recipes.py analyze'"""

import json
import re
from typing import List

from google.protobuf import json_format

from PB.recipe_engine import analyze as analyze_pb
from recipe_engine import recipe_api


class RecipeAnalyzeApi(recipe_api.RecipeApi):
  """A module for calling 'recipes.py analyze'"""

  def is_recipe_affected(self, affected_files: List[str], recipe: str) -> bool:
    """Return True iff changes in <affected_files> affect <recipe>.

    Must be called from the root of a recipes repo (i.e. recipes.py is in the
    cwd).

    Args:
      * affected_files: A list of changed files. Paths may be absolute or
        relative (to the root of the recipes repo), and should use forward
        slashes only.
      * recipe: The name of the recipe to analyze.
    """
    # Example files and test files can't actually affect recipes. However,
    # `recipes.py analyze` thinks they can: see crbug/1476024.
    # To accommodate that, manually filter out examples and tests.
    affected_files = [f for f in affected_files if not _is_example_or_test(f)]

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

    step_data.presentation.logs['input.json'] = json.dumps(analyze_input)

    output_pb = json_format.ParseDict(
        step_data.json.output,
        analyze_pb.Output(),
    )

    if output_pb.invalid_recipes:
      raise recipe_api.StepFailure(
          'recipes analyze failed with invalid recipes: {}'.format(
              output_pb.invalid_recipes))

    if output_pb.error:
      raise recipe_api.StepFailure(
          'recipes analyze failed with error: {}'.format(output_pb.error))

    return recipe in output_pb.recipes


def _is_example_or_test(filepath: str) -> bool:
  """Return whether the filepath points to an example or test file.

  Args:
    filepath: A file in the recipes repo. May be absolute or relative to the
      recipes repo. Must use forward slashes.
  """
  return re.search('recipe_modules/.*/(examples|tests)/', filepath)
