# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building the Cloudready shim."""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
    'depot_tools/gsutil',
    'git',
]

REPO_URL = 'https://chromium.googlesource.com/external/github.com/neverware/shim-build/'
CLOUDREADY_SHIM_BUCKET = 'cloudready-shim'

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  repo_dir = api.path.mkdtemp()
  api.git.clone(REPO_URL, target_path=repo_dir, timeout_sec=3 * 60)

  with api.step.nest('build shim'), api.context(cwd=repo_dir):
    build_log = api.step(
        'make build-no-cache', ['make', 'build-no-cache'],
        stdout=api.raw_io.output(name='stdout', add_output_log=True),
        stderr=api.raw_io.output(name='stderr', add_output_log=True))
    api.step('make copy', ['make', 'copy'])

  gs_dir = "{}-{}".format(api.m.time.utcnow().strftime('%Y-%m-%d'),
                          api.buildbucket.build.id)
  link_name = 'gs publish dir'
  link_value = ('https://console.cloud.google.com/storage/browser/{}/{}'.format(
      CLOUDREADY_SHIM_BUCKET, gs_dir))

  logs = {
      'stdout.txt': build_log.stdout,
      'stderr.txt': build_log.stderr,
  }

  with api.step.nest('upload build logs') as presentation:
    presentation.links[link_name] = link_value
    for f, contents in sorted(logs.items()):
      tmp_log_file = api.path.mkstemp(f)
      api.file.write_raw('write {}'.format(f), tmp_log_file, contents)
      gs_path = api.path.join(gs_dir, f)
      api.gsutil.upload(tmp_log_file, CLOUDREADY_SHIM_BUCKET, gs_path)

  files = {
      '32 bit binary': 'shimia32.efi',
      '64 bit binary': 'shimx64.efi',
  }
  for label, filename in sorted(files.items()):
    with api.step.nest('upload {}'.format(label)) as presentation:
      presentation.links[link_name] = link_value
      bin_path = api.path.abspath(
          api.path.join(api.path['start_dir'], 'install', filename))
      gs_path = api.path.join(gs_dir, filename)
      api.gsutil.upload(bin_path, CLOUDREADY_SHIM_BUCKET, gs_path)


def GenTests(api):
  yield api.test('basic', api.time.seed(1613694623.0))
