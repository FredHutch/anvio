/*
 *  02-13-2021
 *  New version of genome view test for Anvi'o using fabric.js
 */

var VIEWER_WIDTH = window.innerWidth || document.documentElement.clientWidth || document.getElementsByTagName('body')[0].clientWidth;

var canvas;
var genomeMax = 0;
var genomes;

// Settings vars

var spacing; // genome spacing
var showLabels = true; // show genome labels?

var alignToGC = 'GC_X'


function loadAll() {
  document.title = "Testing Genome View"

  canvas = new fabric.Canvas('myCanvas');

  // can either set it on the canvas to check for all arrows, or when arrow is created.
  canvas.on('mouse:down', function(options) {
    if(options.target && options.target.id == 'arrow') {
      options.target.set('fill', options.target.fill=="red" ? "blue" : 'red');
      var testid = options.target.gene.gene_callers_id;
      console.log("Gene cluster: " + idToGC[testid]);
    }
  });

  genomes = [contig437, contig1001, contig798];

  //TESTING
  for(genes of genomes) {
    let g = genes[genes.length-1].stop_in_split;
    if(g > genomeMax) genomeMax = g;
  }
  //canvas.width = genomeMax+200;

  for(var i = 0; i < genomes.length; i++) {
    var genome = genomes[i];
    addGenome(/*genome[1].split.substring(0,6)*/'Genome_'+(i+1), genome, i+1);
  }

  // zooming and panning
  // http://fabricjs.com/fabric-intro-part-5#pan_zoom
  canvas.on('mouse:down', function(opt) {
    var evt = opt.e;
    if (evt.shiftKey === true) {
      this.isDragging = true;
      this.selection = false;
      this.lastPosX = evt.clientX;
      this.lastPosY = evt.clientY;
    }
  });
  canvas.on('mouse:move', function(opt) {
    if (this.isDragging) {
      var e = opt.e;
      var vpt = this.viewportTransform;
      vpt[4] += e.clientX - this.lastPosX;
      vpt[5] += e.clientY - this.lastPosY;
      this.requestRenderAll();
      this.lastPosX = e.clientX;
      this.lastPosY = e.clientY;

      // restrict pan
      /*var vpt = this.viewportTransform;
      var zoom = this.getZoom();
      if (zoom < 400 / 1000) {
        vpt[4] = 200 - 1000 * zoom / 2;
        vpt[5] = 200 - 1000 * zoom / 2;
      } else {
        if (vpt[4] >= 0) {
          vpt[4] = 0;
        } else if (vpt[4] < canvas.getWidth() - 1000 * zoom) {
          vpt[4] = canvas.getWidth() - 1000 * zoom;
        }
        if (vpt[5] >= 0) {
          vpt[5] = 0;
        } else if (vpt[5] < canvas.getHeight() - 1000 * zoom) {
          vpt[5] = canvas.getHeight() - 1000 * zoom;
        }
      }*/
    }
  });
  canvas.on('mouse:up', function(opt) {
    // on mouse up we want to recalculate new interaction
    // for all objects, so we call setViewportTransform
    this.setViewportTransform(this.viewportTransform);
    this.isDragging = false;
    this.selection = true;
  });
  canvas.on('mouse:wheel', function(opt) {
    var delta = opt.e.deltaY;
    var zoom = canvas.getZoom();
    zoom *= 0.999 ** delta;
    if (zoom > 20) zoom = 20;
    if (zoom < 0.01) zoom = 0.01;
    canvas.zoomToPoint({ x: opt.e.offsetX, y: opt.e.offsetY }, zoom);
    opt.e.preventDefault();
    opt.e.stopPropagation();

    // restrict zoom
    /*var vpt = this.viewportTransform;
    if (zoom < 400 / 1000) {
      vpt[4] = 200 - 1000 * zoom / 2;
      vpt[5] = 200 - 1000 * zoom / 2;
    } else {
      if (vpt[4] >= 0) {
        vpt[4] = 0;
      } else if (vpt[4] < canvas.getWidth() - 1000 * zoom) {
        vpt[4] = canvas.getWidth() - 1000 * zoom;
      }
      if (vpt[5] >= 0) {
        vpt[5] = 0;
      } else if (vpt[5] < canvas.getHeight() - 1000 * zoom) {
        vpt[5] = canvas.getHeight() - 1000 * zoom;
      }
    }*/
  });
}

function addGenome(label, gene_list, y) {
  // line
  canvas.add(new fabric.Line([0,0,genomeMax,0], {left: 0,
        top: 30*y - 4,
        stroke: 'black',
        strokeWidth: 2,
        selectable: false}));

  var offsetX = 0;
  if(alignToGC) {
    var targetGeneID = mock_gene_clusters[alignToGC][label];
    var targetGene = gene_list.find(gene => gene.gene_callers_id == targetGeneID);
    var genePos = (targetGene.stop_in_split - targetGene.start_in_split) / 2;
    //var windowCenter = fabric.util.transformPoint({x:canvas.getWidth()/2,y:0}, canvas.viewportTransform)['x'];
    var windowCenter = canvas.getWidth()/2;
    offsetX = windowCenter - genePos;
    console.log(offsetX);
  }

  // here we can either draw genes individually, or collectively as a group
  // grouping allows you to transform them all at once, but makes selecting individual arrows difficult
  // so for now they are drawn individually

  //var geneGroup = new fabric.Group();
  for(gene of gene_list) {
    //addGene(gene, y);
    //geneGroup.addWithUpdate(geneArrow(gene,y));   // IMPORTANT: only way to select is to select the group or use indices. maybe don't group them but some alternative which lets me scale them all at once?
    var geneObj = geneArrow(gene,y);
    if(alignToGC) {
      //geneObj.left += offsetX;
    }
    canvas.add(geneObj);
  }
  //canvas.add(geneGroup.set('scaleX',canvas.getWidth()/genomeMax/3));
  //geneGroup.destroy();
}

function geneArrow(gene, y) {
  var cag = null;
  if(gene.functions) {
      if(gene.functions["COG14_CATEGORY"]) cag = gene.functions["COG14_CATEGORY"][0][0];
      if(gene.functions["COG20_CATEGORY"]) cag = gene.functions["COG20_CATEGORY"][0][0];
  }
  var color = (cag && cag in default_COG_colors) ? default_COG_colors[cag] : 'gray';

  var length = gene.stop_in_split-gene.start_in_split;
  var arrow = new fabric.Path('M 0 0 L ' + length + ' 0 L ' + length + ' 10 L 0 10 M ' + length + ' 0 L ' + length + ' 20 L ' + (25+length) + ' 5 L ' + length + ' -10 z');
  arrow.set({
    id: 'arrow',
    gene: gene,   // better not to store entire gene object, but a pointer/id to find it in the genomes dict?
    selectable: false,
    top: -11+30*y,
    left: 1.5+gene.start_in_split,
    scaleX: 0.5,
    scaleY: 0.5,
    fill: color,
    zoomX: 0.2,
    zoomY: 0.2
  });
  if(gene.direction == 'r') arrow.rotate(180);

  return arrow;
}

///////////////////
var mock_gene_clusters = {'GC_X': {'Genome_1': 14902,
                                   'Genome_2': 19391,
                                   'Genome_3': 18019},
                          'GC_Y': {'Genome_1': 14937,
                                   'Genome_2': 19393,
                                   'Genome_3': 18011}
}

var idToGC = {
  14902: 'GC_X',
  19391: 'GC_X',
  18019: 'GC_X',
  14937: 'GC_Y',
  19393: 'GC_Y',
  18011: 'GC_Y'
}

var mock_genes = [
  {'direction':'r', 'functions':{'COG14_CATEGORY':['K','K',0], 'COG14_FUNCTION':["COG1396", "Transcriptional regulator, contains XRE-family HTH domain", 1.5e-9]}, 'start_in_split':8, 'stop_in_split':29, 'gene_callers_id':22173},
  {'direction':'f', 'functions':null, 'start_in_split':32, 'stop_in_split':150, 'gene_callers_id':2342},
  {'direction':'f', 'functions':null, 'start_in_split':200, 'stop_in_split':280, 'gene_callers_id':123}
]

var mock_genes_0 = [
  {'direction':'f', 'functions':{'COG14_CATEGORY':['C','C',0], 'COG14_FUNCTION':["COG1234", "filler text", 1.5e-9]}, 'start_in_split':50, 'stop_in_split':100, 'gene_callers_id':1234},
  {'direction':'r', 'functions':{'COG14_CATEGORY':['K','K',0], 'COG14_FUNCTION':["COG2327", "filler text", 1.5e-9]}, 'start_in_split':130, 'stop_in_split':150, 'gene_callers_id':2327},
  {'direction':'f', 'functions':{'COG14_CATEGORY':['M','M',0], 'COG14_FUNCTION':["COG2327", "filler text", 1.5e-9]}, 'start_in_split':155, 'stop_in_split':180, 'gene_callers_id':3131},
]

var mock_genes_2 = [
  {'direction':'r', 'functions':{'COG14_CATEGORY':['A','A',0], 'COG14_FUNCTION':["COG1234", "filler text", 1.5e-9]}, 'start_in_split':60, 'stop_in_split':120, 'gene_callers_id':1234},
  {'direction':'f', 'functions':{'COG14_CATEGORY':['C','C',0], 'COG14_FUNCTION':["COG2327", "filler text", 1.5e-9]}, 'start_in_split':140, 'stop_in_split':160, 'gene_callers_id':2327},
  {'direction':'f', 'functions':{'COG14_CATEGORY':['A','A',0], 'COG14_FUNCTION':["COG2327", "filler text", 1.5e-9]}, 'start_in_split':175, 'stop_in_split':190, 'gene_callers_id':3131},
]

var mock_cag_db = {
  'C' : 'steelblue',
  'A' : 'orange',
  'K' : 'red',
  'M' : 'green'
}

// DEPRECATED /////////////////////////////////////////////////////////////////
function addGene(gene, y) {
  var cag = null;
  if(gene.functions) {
      if(gene.functions["COG14_CATEGORY"]) cag = gene.functions["COG14_CATEGORY"][0][0];
      if(gene.functions["COG20_CATEGORY"]) cag = gene.functions["COG20_CATEGORY"][0][0];
  }
  var color = (cag && cag in default_COG_colors) ? default_COG_colors[cag] : 'gray';

  var length = gene.stop_in_split-gene.start_in_split;
  var arrow = new fabric.Path('M 0 0 L ' + length + ' 0 L ' + length + ' 10 L 0 10 M ' + length + ' 0 L ' + length + ' 20 L ' + (25+length) + ' 5 L ' + length + ' -10 z');
  arrow.set({
    id: 'arrow',
    selectable: false,
    top: -11+30*y,
    left: 1.5+gene.start_in_split,
    scaleX: 0.5,
    scaleY: 0.5,
    fill: color,
    zoomX: 0.2,
    zoomY: 0.2
  });
  if(gene.direction == 'r') arrow.rotate(180);
  //arrow.scaleToWidth(.5*canvas.width*(length/genomeMax));

  canvas.add(arrow);
}
