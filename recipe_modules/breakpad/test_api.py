# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_test_api


class BreakpadTestApi(recipe_test_api.RecipeTestApi):

  def find_dmp_files_test_data(self, test_result, filenames):
    return self.step_data(
        'symbolicate dump.symbolicate dumps from {}.find .dmp files'.format(
            test_result.path),
        stdout=self.m.raw_io.output_text('\n'.join(filenames)))

  def minidump_stackwalk_test_data(self, test_result, filename):
    return self.step_data(
        'symbolicate dump.symbolicate dumps from {}.symbolicate {}.minidump_stackwalk'
        .format(test_result.path, filename),
        stdout=self.m.raw_io.output_text('TEST_MINIDUMP_STDOUT'))
