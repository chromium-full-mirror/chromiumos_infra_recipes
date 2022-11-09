# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import json
from typing import Any, Dict

from recipe_engine import recipe_test_api
from recipe_engine.recipe_test_api import TestData


class SigningTestApi(recipe_test_api.RecipeTestApi):

  def setup_mocks(self) -> TestData:
    data = []
    # Set up mocks based on the instructions files from the build_api.
    for instructions in self.m.cros_build_api.INSTRUCTIONS:
      step_data = self.mock_meta(
          instructions + '.json', {
              'status': {
                  'status': 'passed'
              },
              'board': 'eve',
              'type': 'recovery',
              'version': {
                  'full': 'R90-13816.12.0',
                  'platform': '13816.12.0',
                  'milestone': '90'
              },
              'channel': 'dev',
              'keyset': 'eve-mp-v2',
              'keyset_is_mp': True,
              'outputs': {
                  'chromeos_13816.12.0_eve_recovery_dev-channel_mp-v2.bin': {
                      'md5':
                          '637461a912f7d7b3a5cbe52da5bbd5d0',
                      'sha1':
                          '8d1ceff0c6c4ee44870a6ff70920409d1623a0e8',
                      'sha256':
                          '4e68f9ce604bc498831d8733d03ee20101520ac1e4316d822c2491c0e176024c',
                      'size':
                          2688756224
                  },
                  'chromeos_13816.12.0_eve_recovery_dev-channel_mp-v2.bin.zip': {
                      'md5':
                          'bf70b54b9243ac37a0b1fbb13eb14faf',
                      'sha1':
                          'bbd75884fb404d8655b23e2b09885806dec3cde0',
                      'sha256':
                          '508f55221dc7102b981407d059d921e7bc7281f784e42a6aa806eae91e4bc55b',
                      'size':
                          1360494460
                  }
              },
              'key_versions': {
                  'firmware_key_version': 1,
                  'firmware_version': 1,
                  'kernel_key_version': 1,
                  'kernel_version': 1
              }
          }, prestep='get signed build metadata.')
      data.append(step_data)

    result = data[0]
    for dd in data[1:]:
      result += dd
    return result

  def mock_meta(self, file_name: str, data: Dict[str, Any], retcode: int = 0,
                run: int = 1, prestep: str = '') -> TestData:
    """Mock the response for looking up a provided instructions file.

    Args:
      file_name: File being looked up from GS.
      data: Dict of data to be the response (in JSON).
      retcode: Return code of the lookup (default 0).
      run: Number of the run (default 1) for the step name.
      prestep: A parent step wrapping the gsutil call.

    Returns:
      TestData object (for chaining within `yield` statements).
    """
    return self.mock_meta_str(file_name, json.dumps(data), retcode=retcode,
                              run=run, prestep=prestep)

  def mock_meta_str(self, file_name: str, data_string: str, retcode: int = 0,
                    run: int = 1, prestep: str = '') -> TestData:
    """Mock the response for looking up a provided instructions file.

    Args:
      file_name: File being looked up from GS.
      data_string: String of JSON to be returned.
      retcode: Return code of the lookup (default 0).
      run: Number of the run (default 1) for the step name.
      prestep: A parent step wrapping the gsutil call.

    Returns:
      TestData object (for chaining within `yield` statements).
    """
    run_num = '' if run == 1 else ' ({run})'.format(run=run)
    return self.step_data(
        '{prestep}wait for signing to complete'
        '.gsutil reading instructions for {file}{run}'.format(
            file=file_name, run=run_num, prestep=prestep),
        stdout=self.m.raw_io.output(data_string), retcode=retcode)
