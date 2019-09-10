# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for creating task URLs out of complex data structures."""

from recipe_engine import recipe_api
from PB.test_platform.taskstate import TaskState


class UrlsApi(recipe_api.RecipeApi):
  """A module for creating links to tasks."""

  def get_build_link_map(self, build):
    """Returns the title->URL to the given buildbucket build.

    Args:
      build (Build): The buildbucket build in question.

    Returns:
      str->str: title->URL pointing to the build milo page.
    """
    link_url = self.m.buildbucket.build_url(build_id=build.id)
    return {'build page': link_url}

  def get_vm_test_link_map(self, vm_test):
    """Returns the title->URL to the given vm test.

    Args:
      vm_test (Build): The vm test in question.

    Returns:
      str->str: title->URL pointing to the vm_test's milo page.
    """
    link_url = self.m.buildbucket.build_url(build_id=vm_test.id)
    return {'test page': link_url}

  def get_skylab_task_url(self, skylab_task):
    """Returns the URL to the given skylab task.

    Args:
      skylab_task (SkylabTask): The Skylab task in question.

    Returns:
      str: URL pointing to the skylab swarming task page.
    """
    return skylab_task.url

  def get_skylab_result_link_map(self, skylab_result):
    """Returns the URL to the given skylab result page.

    Args:
      skylab_task (SkylabResult): The Skylab result in question.

    Returns:
      str->str map: title to URL to the skylab swarming task page
      if the suite succeeded or entries of just the failed tests.
    """
    if skylab_result.success or not skylab_result.child_results:
      link_url = self.get_skylab_task_url(skylab_result.task)
      return {'suite page': link_url}
    else:
      link_map = {}
      for task_result in skylab_result.child_results:
        if task_result.state.verdict in (TaskState.VERDICT_FAILED,
                                         TaskState.VERDICT_UNSPECIFIED):
          link_map[task_result.name] = task_result.task_url

      return link_map

  def get_gs_path_url(self, gs_path):
    """Returns the Cloud Storage Browser URL to the given GS path.

    Args:
      gs_path (str): A string of the format "gs://<bucket>/<object>"

    Returns:
      str: URL pointing to the Cloud Storage Browser page for the
        object.
    """

    if not gs_path.startswith('gs://'):
      raise ValueError('gs_path argument must start with "gs://"')

    return 'https://storage.cloud.google.com/' + gs_path.lstrip('gs://')
