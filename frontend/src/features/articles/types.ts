export interface ArticleAuthor {
  id: number;
  username: string;
}

export interface ArticleListItem {
  id: number;
  title: string;
  author: ArticleAuthor;
  created_at: string;
}

export interface Article extends ArticleListItem {
  content: string;
  updated_at: string;
}

export interface CreateArticleInput {
  title: string;
  content: string;
}

export interface UpdateArticleInput {
  title?: string;
  content?: string;
}
