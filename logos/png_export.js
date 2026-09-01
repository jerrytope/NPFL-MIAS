/* ==========================================================================
   Shared "Download PNG" helper — dashboard and Super Computer
   ==========================================================================

   Lives in logos/ because that directory is STATICFILES_DIRS[0], so it is
   served at /static/png_export.js and both apps can load it. The dashboard and
   the Super Computer templates are separate standalone documents with no
   common base, so a shared static file is the only place this can live once.

   Deliberately defined on `window` rather than inside a DOMContentLoaded
   closure, because the buttons call it from inline onclick="" attributes,
   which run in global scope.

   Four things this handles that a bare html2canvas call does not:

   1. DARK MODE. Every card here is styled with semi-transparent backgrounds
      (--glass-bg). Capturing a dark-theme card onto a white canvas composites
      near-white text onto white and produces an unreadable image. The clone is
      forced to data-theme="light" before capture, so the PNG is always the
      light treatment on white regardless of what the viewer is looking at.

   2. THE BUTTON ITSELF. The download button usually sits inside the element
      being captured. Hidden in the clone, or every exported image has a
      download icon stamped in the corner.

   3. ANIMATIONS. Probability bars animate their width in from 0, and
      high-confidence prediction cards run an infinite pulse-glow. Capturing
      mid-flight gives a card with empty bars or a random glow state. All
      animation and transition is disabled in the clone.

   4. LAZY IMAGES. Team crests are <img loading="lazy">. One that has not
      entered the viewport has not decoded, and html2canvas draws nothing for
      it. Every image inside the target is decoded before capture.
   ========================================================================== */

(function () {
    'use strict';

    var slugify = function (s) {
        return String(s || '').trim().replace(/[^a-z0-9]+/gi, '-').replace(/^-+|-+$/g, '');
    };

    /* Wait for every image inside `element` to be decodable. A crest that
       fails (404, blocked) is skipped rather than rejecting the whole export —
       a missing badge is a much smaller problem than no image at all. */
    function decodeImages(element) {
        var images = Array.prototype.slice.call(element.querySelectorAll('img'));
        return Promise.all(images.map(function (img) {
            img.loading = 'eager';
            if (img.complete && img.naturalWidth > 0) return Promise.resolve();
            if (typeof img.decode === 'function') {
                return img.decode().catch(function () { /* skip broken crest */ });
            }
            return new Promise(function (resolve) {
                img.addEventListener('load', resolve, { once: true });
                img.addEventListener('error', resolve, { once: true });
            });
        }));
    }

    /* Strip anything from the clone that would spoil a still image. */
    function prepareClone(clonedDoc) {
        clonedDoc.documentElement.setAttribute('data-theme', 'light');

        var style = clonedDoc.createElement('style');
        style.textContent = [
            '*,*::before,*::after{',
            '  animation:none !important;',
            '  transition:none !important;',
            '}',
            '.download-btn{display:none !important;}',
            /* Semi-transparent card backgrounds composite badly onto white. */
            '.prediction-card,.scoreline-card,.summary-capture,.card,.kpi-card{',
            '  background:#ffffff !important;',
            '  backdrop-filter:none !important;',
            '}'
        ].join('');
        clonedDoc.head.appendChild(style);
    }

    /**
     * Save an element as a PNG on a white background.
     *
     * @param {string|HTMLElement} target   element, or its id
     * @param {string} filenamePrefix       used as the filename stem
     * @param {string} [nameHint]           overrides the auto "team-vs-team" prefix
     */
    function downloadElementAsPNG(target, filenamePrefix, nameHint) {
        var element = (typeof target === 'string')
            ? document.getElementById(target)
            : target;

        if (!element) {
            console.error('downloadElementAsPNG: no element for', target);
            return;
        }
        if (typeof html2canvas === 'undefined') {
            alert('The image library did not load. Check your connection and try again.');
            return;
        }

        /* On the dashboard the two selected teams name the file. On the Super
           Computer those elements do not exist, so the caller passes a hint. */
        var prefix = '';
        if (nameHint) {
            prefix = slugify(nameHint) + '-';
        } else {
            var t1 = document.getElementById('t1Name');
            var t2 = document.getElementById('t2Name');
            if (t1 && t2) {
                prefix = slugify(t1.innerText) + '-vs-' + slugify(t2.innerText) + '-';
            }
        }

        /* An element can ask to be laid out differently just for the capture by
           setting data-export-class (e.g. the head-to-head summary switches its
           four KPI cards from one wide row to a 2x2 block, so the PNG is a
           usable shape rather than a thin strip).

           This has to be applied to the LIVE element, not to the clone:
           html2canvas sizes its canvas from the original element's bounding
           box, so a clone that ended up taller would simply be cropped. The
           cost is a brief layout shift on screen while the capture runs. */
        var exportClass = element.dataset ? element.dataset.exportClass : '';
        function setExportLayout(on) {
            if (!exportClass) return;
            element.classList[on ? 'add' : 'remove'](exportClass);
        }

        setExportLayout(true);

        decodeImages(element).then(function () {
            return html2canvas(element, {
                backgroundColor: '#ffffff',
                scale: 2,
                useCORS: true,          /* Google Fonts / FontAwesome are cross-origin */
                logging: false,
                onclone: function (clonedDoc) { prepareClone(clonedDoc); }
            });
        }).then(function (canvas) {
            setExportLayout(false);
            var link = document.createElement('a');
            link.download = prefix + filenamePrefix + '.png';
            link.href = canvas.toDataURL('image/png');
            document.body.appendChild(link);
            link.click();
            link.remove();
        }).catch(function (err) {
            /* Must also run here, or a failed export leaves the page stuck in
               the export layout. */
            setExportLayout(false);
            console.error('Failed to generate download image:', err);
            alert('Could not generate the download image. Please try again.');
        });
    }

    window.downloadElementAsPNG = downloadElementAsPNG;
})();
