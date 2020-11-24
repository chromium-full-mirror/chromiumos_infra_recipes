# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class RepoTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the repo module."""

  @property
  def test_projects(self):
    """Returns a list of repo project names to use for testing."""
    return ['project-a', 'project-b', 'project-c']

  def local_manifest_step_test_data(self):
    """Returns test data to simulate a local manifest."""
    test_manifest = """
<manifest>
  <remote name="cros-internal"
          fetch="https://chrome-internal.googlesource.com"
          review="https://chrome-internal-review.googlesource.com" />
  <project name="chromeos/private-repo1"
     path="src/private-repo1"
     remote="cros-internal" />
</manifest>
    """

    return self.m.gitiles.make_encoded_file(test_manifest)

  def project_infos_test_data(self, data=None):
    """Return step_test_data for project_infos().

    Args:
      data (list[dict]): A list of dictionaries with:
        project (str): The name of the project.
        path (str): The tree relpath.  Default: src/{project}.
        remote (str): The remote.  Default: cros.
        rrev (str): The remote revision.  Default: refs/heads/master.
        upstream (str): The upstream revision. Default: refs/heads/master.

    Returns:
      step_test_data for the step.
    """
    data = data or [dict(project=p) for p in self.test_projects]

    def _generate(x):
      p = x['project']
      return dict(project=p, path=x.get('path', 'src/%s' % p),
                  rrev=x.get('rrev', 'refs/heads/master'),
                  upstream=x.get('upstream', 'refs/heads/master'),
                  remote=x.get('remote', 'cros'))

    return '\n'.join(
        '{project}|{path}|{remote}|{rrev}|{upstream}'.format(**_generate(x))
        for x in data)

  def project_infos_step_data(self, step='', data=None, iteration=1):
    """Return step_test_data for a call to project_infos().

    Args:
      step (str): Name of the step.
      data (list[dict]): A list of dictionaries with:
        project (str): The name of the project.
        path (str): The tree relpath.  Default: src/{project}.
        remote (str): The remote.  Default: cros.
        rrev (str): The remote revision.  Default: refs/heads/master.
        upstream (str): The upstream revision. Default: refs/heads/master.
      iteration (int): Which call this applies to for this step/endpoint.

    Returns:
      step_test_data for the step.
    """
    name = '%s.' % step if step else ''
    name += 'repo forall'
    name += '' if iteration == 1 else ' (%d)' % iteration
    content = self.project_infos_test_data(data)
    return self.step_data(name, stdout=self.m.raw_io.output(content))
