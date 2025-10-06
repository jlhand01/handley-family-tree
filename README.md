# Handley Family Tree Website Generator

This repository contains a small Python script that reads the `handley.ged`
GEDCOM file and produces a static website highlighting the descendants of
David Handley and Verna Mae Rucker Handley.

## Usage

```bash
python generate_family_tree.py handley.ged site
```

The command above builds the site into the `site/` directory. The generated
`index.html` shows David and Verna on the left with their children arranged in
a column on the right. Every descendant has a dedicated page (located in
`site/people/`) that presents the person's details, followed by any biography,
and then a list of their children so you can continue navigating through the
generations.

You can provide alternative base individuals by passing name fragments
or, if necessary, a specific family identifier:

```bash
python generate_family_tree.py handley.ged site \
    --base-husband "David Handley" \
    --base-wife "Verna Mae Rucker Handley" \
    --base-family-id @F2@
```

The `--base-family-id` option is optional and only needed if the script cannot
uniquely identify the couple based on names alone.

## Viewing the Site

After running the script open `site/index.html` in your browser. Click a child
to drill down into their branch, then use the links on each page to continue
through the family tree or return to the main page.

## Updating Word Biographies

The `.docx` biographies stored in the repository can be edited directly without
re-running the site generator. To update them:

1. Copy the document you want to change from the repository to your computer.
2. Make the edits in Microsoft Word (or another editor that can save `.docx`
   files) and save the file with the same name.
3. Replace the original file in the repository with your updated version.
4. Stage and commit the change so the new document is tracked in version
   control.

You can also add new biographies by dropping additional `.docx` files into the
repository and committing them. Keeping the filenames descriptive (for example,
`First Last.docx`) makes them easier to locate later.

## Continuous Deployment

Pushing to the `main` branch automatically rebuilds the site with GitHub
Actions. The workflow runs `generate_family_tree.py` and publishes the contents
of the `site/` directory directly to GitHub Pages, so the public site stays in
sync with the latest GEDCOM data. If you want to check the generated files
before committing, run the command above locally and open `site/index.html`.
