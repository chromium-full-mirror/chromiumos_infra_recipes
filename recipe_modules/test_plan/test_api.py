# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_test_api

class TestPlanTestApi(recipe_test_api.RecipeTestApi):
  # TODO(yshaul): Update artifact_path when field is implemented.
  #               crbug/935152
  def example_hw_unit(self,
                   test_env='hw',
                   test_suite='test-suite',
                   reference_design=None,
                   build_target=None,
                   image_name='image.bin',
                   artifact_path='path/to/artifact'):

    scheduling_requirements = get_scheduling_requirements(
      reference_design=reference_design,
      build_target=build_target,
    )

    return {
      'test_env': test_env,
      'test_suite': test_suite,
      'scheduling_requirements': scheduling_requirements,
      'build_payload': {
        'artifact_path': artifact_path,
        'image': [
          {
            'image_name': image_name
          }
        ]
      }
    }

def get_scheduling_requirements(reference_design=None, build_target=None):
  """Get scheduling requirements.
  
  Returns:
    SchedulingRequirements
  """
  if reference_design is not None:
    return {
      'reference_design': reference_design
    }
  elif build_target is not None:
    return {
      'build_target': build_target
    }

  return {}
