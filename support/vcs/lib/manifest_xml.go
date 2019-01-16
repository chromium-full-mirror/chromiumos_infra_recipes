package lib

import (
	"encoding/xml"
	"os"
)

type Manifest struct {
	XMLName   xml.Name  `xml:"manifest"`
	Projects  []Project `xml:"project"`
	Remotes   []Remote  `xml:"remote"`
	Notice    string    `xml:"notice"`
	RepoHooks RepoHooks `xml:"repo-hooks"`
}

type Project struct {
	XMLName     xml.Name     `xml:"project"`
	Annotations []Annotation `xml:"annotation"`
	CopyFile    CopyFile     `xml:"copyfile"`
	Groups      string       `xml:"groups,attr"`
	Name        string       `xml:"name,attr"`
	Path        string       `xml:"path,attr"`
	Remote      string       `xml:"remote,attr"`
	Revision    string       `xml:"revision,attr"`
	SyncC       bool         `xml:"sync-c,attr"`
	Upstream    string       `xml:"upstream,attr"`
}

type Remote struct {
	XMLName xml.Name `xml:"remote"`
	Fetch   string   `xml:"fetch,attr"`
	Name    string   `xml:"name,attr"`
	Review  string   `xml:"review,attr"`
}

type RepoHooks struct {
	XMLName     xml.Name `xml:"repo-hooks"`
	EnabledList string   `xml:"enabled-list,attr"`
	InProject   string   `xml:"in-project,attr"`
}

type CopyFile struct {
	XMLName xml.Name `xml:"copyfile"`
	Dest    string   `xml:"dest,attr"`
	Src     string   `xml:"src,attr"`
}

type Annotation struct {
	XMLName xml.Name `xml:"annotation"`
	Name    string   `xml:"name,attr"`
	Value   string   `xml:"value,attr"`
}

type ManifestDiff struct {
	ChangedProjects     []ProjectDiff `json:"changed_projects"`
	AddedProjectPaths   []string      `json:"added_project_paths"`
	RemovedProjectPaths []string      `json:"removed_project_paths"`
}

type ProjectDiff struct {
	Path    string `json:"path"`
	FromRev string `json:"from_rev"`
	ToRev   string `json:"to_rev"`
}

func (m *Manifest) LoadFromXmlFile(path string) error {
	// Open the file
	xmlFile, err := os.Open(path)
	if err != nil {
		return err
	}
	defer xmlFile.Close()

	if err := xml.NewDecoder(xmlFile).Decode(m); err != nil {
		return nil
	}

	return nil
}

func (m Manifest) Diff(to Manifest) ManifestDiff {
	fromByPath := m.projectPathMap()
	toByPath := to.projectPathMap()
	var manifestDiff ManifestDiff

	// Gather diffs (exist in both)
	for _, p := range m.Projects {
		if toProj, ok := toByPath[p.effectivePath()]; ok && p.Revision != toProj.Revision {
			manifestDiff.ChangedProjects = append(manifestDiff.ChangedProjects, ProjectDiff{
				p.effectivePath(),
				p.Revision,
				toProj.Revision,
			})
		}
	}

	// Gather added projects (only in `to`)
	for _, p := range to.Projects {
		if _, ok := fromByPath[p.effectivePath()]; !ok {
			manifestDiff.AddedProjectPaths = append(manifestDiff.AddedProjectPaths, p.effectivePath())
		}
	}

	// Gather removed projects (only in `from`)
	for _, p := range m.Projects {
		if _, ok := toByPath[p.effectivePath()]; !ok {
			manifestDiff.RemovedProjectPaths = append(manifestDiff.RemovedProjectPaths, p.effectivePath())
		}
	}

	return manifestDiff
}

func (m Manifest) projectPathMap() map[string]Project {
	byPath := make(map[string]Project)
	for _, p := range m.Projects {
		byPath[p.effectivePath()] = p
	}
	return byPath
}

func (p Project) effectivePath() string {
	if p.Path == "" {
		return p.Name
	}
	return p.Path
}
