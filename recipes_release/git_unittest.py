#!/usr/bin/env vpython3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

import git


class TrimTrivialSuffixTest(unittest.TestCase):

  def test_success(self):
    changes = [
        # Changes are out of order.
        git.Commit('500', '', 'Roll recipe dependencies (trivial).', '',
                   '2020-01-01T16:00:00+00:00'),
        git.Commit('100', '', '', '', '2020-01-01T12:00:00+00:00'),
        git.Commit('200', '', 'Roll recipe dependencies (trivial).', '',
                   '2020-01-01T13:00:00+00:00'),
        git.Commit('300', '', '', '', '2020-01-01T14:00:00+00:00'),
        git.Commit('400', '', 'Roll recipe dependencies (trivial).', '',
                   '2020-01-01T15:00:00+00:00'),
    ]
    trimmed_changes = git.trim_trivial_suffix(changes)
    self.assertEqual(trimmed_changes, sorted(changes)[:3])

  def test_success_all_trivial(self):
    changes = [
        git.Commit('100', '', 'Roll recipe dependencies (trivial).', '',
                   '2020-01-01T15:00:00+00:00'),
        git.Commit('200', '', 'Roll recipe dependencies (trivial).', '',
                   '2020-01-01T16:00:00+00:00'),
    ]
    trimmed_changes = git.trim_trivial_suffix(changes)
    self.assertEqual(trimmed_changes, [])


if __name__ == '__main__':
  unittest.main()
