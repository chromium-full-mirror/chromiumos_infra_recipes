# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to archive test results to CTS specific buckets"""

import json

from recipe_engine import recipe_api


class CTSResultsArchive(recipe_api.RecipeApi):
  """API to archive test results to CTS specific buckets"""

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self._properties = properties

  def archive(self, d_dir):
    """Archive CTS result files to CTS specific GS buckets.

    This module determines if any CTS results files should uploaded to the CTS
    GS buckets and archives them if required.

    @param d_dir: The results directory to process.
    """
    # BUG(b/244294904, b/244297392): Some tags may not exist all the time; apply
    # same workaround as https://crrev.com/c/3864300
    model = self.m.cros_tags.get_single_value('label-model')
    if not model:
      model = self.m.cros_tags.get_single_value(
          'label-model', self.m.buildbucket.swarming_bot_dimensions)
    build = self.m.cros_tags.get_single_value('build')
    if not build:
      build = self.m.cros_tags.get_single_value('label-image')

    with self.m.step.nest('Archive CTS results') as step:
      parent_task_id = self.m.cros_tags.get_single_value('parent_task_id')
      # Can be missing in led-triggered runs
      if not parent_task_id:
        step.step_text = 'skipped due to missing parent_task_id'
        return

      json_input = {
          'dir': d_dir,
          'cts_results_gsurl': self._properties.cts_results_gsurl,
          'cts_apfe_gsurl': self._properties.cts_apfe_gsurl,
          'build': build,
          'model': model,
          'parent_job_id': parent_task_id,
      }
      step.logs['json_input'] = json.dumps(json_input, sort_keys=True)
      result = self.m.step(
          'prepare uploads',
          [
              'python3',
              self.resource('prepare_uploads.py'),
              '--json-input',
              self.m.json.input(json_input),
              '--json-output',
              self.m.json.output(),
          ],
          infra_step=True,
          step_test_data=lambda: self.m.json.test_api.output({
              'instructions': [{
                  'name': 'fake-instruction',
                  'source': 'local/directory/to/upload',
                  'destination': 'gs://fake-bucket/fake-folder',
              }]
          }),
      )
      instructions = result.json.output.get('instructions')
      step.logs['instructions'] = str(instructions)

      with self.m.step.nest('Upload prepared results') as step:
        for i, ins in enumerate(instructions):
          # Response format
          name = ins['name']
          source = ins['source']
          destination = ins['destination']

          self.m.gsutil(['-m', 'cp', '-eR', source, destination])
          url = 'https://console.cloud.google.com/storage/browser/%s' % (
              destination[len('gs://'):],)
          step.links['%d:%s' % (i, name)] = url
