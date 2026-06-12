import { createBrowserRouter, Navigate } from 'react-router-dom';
import { LoginPage } from '@/pages/LoginPage';
import { DashboardPage } from '@/pages/DashboardPage';
import { AppLayout } from '@/layout/AppLayout';
import { RequireAuth } from '@/auth/RequireAuth';
import { DataframeListPage } from '@/features/dataframe/pages/DataframeListPage';
import { DataframeEditorPage } from '@/features/dataframe/pages/DataframeEditorPage';
import { ProductListPage } from '@/features/product/pages/ProductListPage';
import { ProductDetailPage } from '@/features/product/pages/ProductDetailPage';
import { ProductEditorPage } from '@/features/product/pages/ProductEditorPage';
import { CategoriesPage } from '@/features/product/pages/CategoriesPage';
import { BrandsPage } from '@/features/product/pages/BrandsPage';
import { CharacteristicTypesPage } from '@/features/product/pages/CharacteristicTypesPage';
import { ImportPage } from '@/features/product/pages/ImportPage';
import { CategoryImportPage } from '@/features/product/pages/CategoryImportPage';
import { CategoryDetailPage } from '@/features/product/pages/CategoryDetailPage';
import { SuppliersPage } from '@/features/supplier/pages/SuppliersPage';
import { SupplierDetailPage } from '@/features/supplier/pages/SupplierDetailPage';
import { FeedMappingCreatePage } from '@/features/supplier/pages/FeedMappingCreatePage';
import { FeedMappingEditPage } from '@/features/supplier/pages/FeedMappingEditPage';
import { SupplierFeedPage } from '@/features/supplier/pages/SupplierFeedPage';
import { FeedQueuePage } from '@/features/supplier/pages/FeedQueuePage';
import { SupplierLinksPage } from '@/features/supplier/pages/SupplierLinksPage';
import { PriceTypesPage } from '@/features/pricing/pages/PriceTypesPage';

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'suppliers', element: <SuppliersPage /> },
      { path: 'suppliers/:id', element: <SupplierDetailPage /> },
      { path: 'suppliers/:id/mappings/new', element: <FeedMappingCreatePage /> },
      { path: 'suppliers/:id/mappings/:mappingId/edit', element: <FeedMappingEditPage /> },
      { path: 'suppliers/:id/feeds/:feedId', element: <SupplierFeedPage /> },
      { path: 'suppliers/:id/feeds/:feedId/queue', element: <FeedQueuePage /> },
      { path: 'suppliers/:id/links', element: <SupplierLinksPage /> },
      { path: 'products', element: <ProductListPage /> },
      { path: 'products/new', element: <ProductEditorPage /> },
      { path: 'products/import', element: <ImportPage /> },
      { path: 'products/categories', element: <CategoriesPage /> },
      { path: 'products/categories/import', element: <CategoryImportPage /> },
      { path: 'products/categories/:id', element: <CategoryDetailPage /> },
      { path: 'products/brands', element: <BrandsPage /> },
      { path: 'products/characteristics', element: <CharacteristicTypesPage /> },
      { path: 'products/:id', element: <ProductDetailPage /> },
      { path: 'products/:id/edit', element: <ProductEditorPage /> },
      { path: 'prices', element: <PriceTypesPage /> },
      { path: 'dataframe', element: <DataframeListPage /> },
      { path: 'dataframe/new', element: <DataframeEditorPage /> },
      { path: 'dataframe/:id', element: <DataframeEditorPage /> },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
]);
