# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class GitClTestApi(recipe_test_api.RecipeTestApi):

  def output(self, step_name, output):
    return self.step_data(step_name, self.m.raw_io.stream_output(output))

  def issues(self, parent_step, issue_map):
    output = '\n'.join([
        'Branch for issue number {}: {}'.format(issue, ref)
        for ref, issue in issue_map.items()
    ])
    step_name = parent_step + ('.' if parent_step else '') + 'git_cl issue'
    return self.step_data(step_name, self.m.raw_io.stream_output(output))
