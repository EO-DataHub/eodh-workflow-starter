cwlVersion: v1.2
$namespaces:
  s: https://schema.org/
# Must equal the pyproject.toml version and the dockerPull tag. Change all three with `make bump VERSION=x.y.z`.
s:softwareVersion: 0.1.0
schemas:
  - http://schema.org/version/9.0/schemaorg-current-http.rdf

$graph:
  # The Workflow's id is the workflow ID on the Hub.
  - class: Workflow
    id: eodh-workflow-starter-ndvi
    label: NDVI (EODH workflow starter example)
    doc: Computes NDVI from a STAC item's red and nir bands and writes a COG with renderable STAC.
    requirements:
      # The runner sizes the job's pods from the largest ResourceRequirement in the file.
      - class: ResourceRequirement
        coresMax: 2
        ramMax: 2048
    inputs:
      stac_item:
        label: STAC item
        doc: The STAC item to compute NDVI from. It needs assets with red and nir bands.
        type: Directory
    outputs:
      - id: results
        type: Directory
        outputSource:
          - main/results
    steps:
      main:
        run: "#main-tool"
        in:
          stac_item_dir: stac_item
        out: [results]

  - class: CommandLineTool
    id: main-tool
    requirements:
      - class: ResourceRequirement
        coresMax: 1
        ramMax: 512
    hints:
      DockerRequirement:
        dockerPull: ghcr.io/eo-datahub/eodh-workflow-starter:0.1.0
    baseCommand: ["python3", "/app/main.py"]
    inputs:
      stac_item_dir:
        type: Directory
        inputBinding:
          prefix: --stac_item_dir=
          separate: false
          valueFrom: $(self.path)
    outputs:
      results:
        type: Directory
        outputBinding:
          glob: "."
