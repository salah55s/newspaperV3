# newspaperV3

An advanced library for news extraction, article parsing, and content analysis. This is a fork/version based on the original `newspaper` library by Lucas Ou-Yang.

## Installation

Install the package using pip:

```bash
pip install newspaperV3
```

## Basic Usage

Here's a simple example of how to download and parse an article:

```python
from newspaperV3 import Article
import nltk

# NLTK data is required for the first run
# nltk.download('punkt')

url = 'https://edition.cnn.com/2025/07/29/middleeast/israeli-settler-odeh-hathalin-west-bank-oscar-intl'

# Create an Article object
article = Article(url)

# Download and parse the article
article.download()
article.parse()

# Perform Natural Language Processing (NLP)
article.nlp()

# Print the results
print("Title:", article.title)
print("Authors:", article.authors)
print("Publish Date:", article.publish_date)
print("Top Image:", article.top_image)
print("\nSummary:")
print(article.summary)
print("\nKeywords:", article.keywords)
```

## Features

* **Article Extraction** : Automatically extract clean article text from web pages
* **Metadata Parsing** : Extract titles, authors, publication dates, and images
* **Natural Language Processing** : Generate summaries and extract keywords
* **Multi-language Support** : Process articles in various languages
* **Image Processing** : Extract and analyze article images
* **Content Analysis** : Advanced text processing and analysis capabilities

## Requirements

* Python 3.6+
* NLTK (for natural language processing)
* Additional dependencies installed automatically

## License

This project is licensed under the MIT License.
