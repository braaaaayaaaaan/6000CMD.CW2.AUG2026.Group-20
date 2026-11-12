import { configureStore } from "@reduxjs/toolkit";
import searchReducer from "@/app/searchSlice";

export const makeStore = () => configureStore({ reducer: { search: searchReducer } });
