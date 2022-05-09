# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

from recipe_engine import recipe_test_api


class RepoTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the repo module."""

  @staticmethod
  def _read_test_file(filename):
    """Read the content of a file in this directory.

    Args:
      filename (str): The basename of the file (located in this directory) to
          read.

    Returns:
      (str): The contents of the file.
    """
    with open(
        os.path.join(os.path.abspath(os.path.dirname(__file__)),
                     filename)) as f:
      return f.read().strip()

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
        rrev (str): The remote revision.  Default: from src_state.
        upstream (str): The upstream revision. Default: from src_state.

    Returns:
      step_test_data for the step.
    """
    data = ([dict(project=p) for p in self.test_projects]
            if data is None else data)

    def _generate(x):
      p = x['project']
      default_ref = self.m.src_state.default_ref
      return dict(project=p, path=x.get('path', 'src/%s' % p),
                  rrev=x.get('rrev', default_ref),
                  upstream=x.get('upstream',
                                 default_ref), remote=x.get('remote', 'cros'))

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
        rrev (str): The remote revision.  Default: from src_state.
        upstream (str): The upstream revision. Default: from src_state.
      iteration (int): Which call this applies to for this step/endpoint.

    Returns:
      step_test_data for the step.
    """
    name = '%s.' % step if step else ''
    name += 'repo forall'
    name += '' if iteration == 1 else ' (%d)' % iteration
    content = self.project_infos_test_data(data)
    return self.step_data(name, stdout=self.m.raw_io.output_text(content))

  @recipe_test_api.mod_test_data
  @staticmethod
  def repo_current_state(value):
    return value

  @recipe_test_api.mod_test_data
  @staticmethod
  def repo_manifest_branch(value):
    return value

  @recipe_test_api.mod_test_data
  @staticmethod
  def fail_repo_sync(value):
    return value

  @classmethod
  def repo_event_log_text(cls):
    return cls._read_test_file('repo_event_log.jsonl')
