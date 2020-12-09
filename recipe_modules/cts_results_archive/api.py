# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to archive test results to CTS specific buckets"""

from recipe_engine import recipe_api


class CTSResultsArchive(recipe_api.RecipeApi):
  """API to archive test results to CTS specific buckets"""

  def __init__(self, properties, **kwargs):
    super(CTSResultsArchive, self).__init__(**kwargs)
    self._properties = properties

  def archive(self, dir):
    """Archive CTS result files to CTS specific GS buckets.

    This module determines if any CTS results files should uploaded to the CTS
    GS buckets and archives them if required.

    @param dir: The results directory to process.
    """
    with self.m.step.nest('Archive CTS results') as step:
      json_input = {
          'dir': dir,
          'cts_results_gsurl': self._properties.cts_results_gsurl,
          'cts_apfe_gsurl': self._properties.cts_apfe_gsurl,
      }
      step.logs['json_input'] = str(json_input)
      result = self.m.python(
          'prepare uploads',
          self.resource('prepare_uploads.py'),
          [
              '--json-input',
              self.m.json.input(json_input),
              '--json-output',
              self.m.json.output(),
          ],
          step_test_data=lambda: self.m.json.test_api.output({
              'instructions': [{
                  'name': 'fake-instruction',
                  'source': 'local/directory/to/upload',
                  'destination': 'gs://fake-bucket/fake-folder',
              }]
          }),
      )
      instructions = result.json.output.get('instructions')
      step.logs['instructions'] = [str(instructions)]

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
