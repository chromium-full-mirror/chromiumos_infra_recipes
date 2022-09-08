# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class BreakpadTestApi(recipe_test_api.RecipeTestApi):

  def find_dmp_files_test_data(self, test_result, filenames):
    return self.step_data(
        'symbolicate dump.symbolicate dumps from {}.find .dmp files'.format(
            test_result.log_data.gs_url),
        stdout=self.m.raw_io.output(b'\n'.join(filenames)))

  def minidump_stackwalk_test_data(self, test_result, filename, retcode=None):
    return self.step_data(
        'symbolicate dump.symbolicate dumps from {}.symbolicate {}.minidump_stackwalk'
        .format(test_result.log_data.gs_url, filename),
        stdout=self.m.raw_io.output(b'TEST_MINIDUMP_STDOUT'), retcode=retcode)

  def gsutil_download_test_data(self, retcode=None):
    return self.step_data(
        'symbolicate dump.gsutil download_url',
        stdout=self.m.raw_io.output(b'TEST_GSUTIL_DOWNLOAD_STDOUT'),
        retcode=retcode)
